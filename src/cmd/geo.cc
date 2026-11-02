// geo.cc -- Redis-compatible geospatial commands backed by sorted sets.
//
// Coordinates use the public 52-bit geohash scheme (26 longitude bits interleaved with 26
// latitude bits). All key access stays on the shard owner through the narrow t_zset.h bridge.
#include "geo.h"

#include "blocking.h"
#include "command.h"
#include "notify.h"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <string_view>
#include <vector>

#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../store/flatstore.h"

namespace tomo {
namespace {

constexpr double kLatitudeMax = 85.05112878;
constexpr double kEarthRadiusMeters = 6372797.560856;
constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr uint64_t kAxisCells = uint64_t{1} << 26;

enum class GeoShape : uint8_t { Radius, Box };
enum class GeoOrder : uint8_t { None, Asc, Desc };

struct GeoSearchOptions {
    bool from_member = false;
    Slice member;
    double longitude = 0;
    double latitude = 0;
    GeoShape shape = GeoShape::Radius;
    double radius_m = 0;
    double width_m = 0;
    double height_m = 0;
    double unit_m = 1;
    GeoOrder order = GeoOrder::None;
    uint64_t count = 0;
    bool any = false;
    bool with_coord = false;
    bool with_dist = false;
    bool with_hash = false;
    bool store = false;
    bool store_distance = false;
    uint32_t source_arg = 1;
    uint32_t destination_arg = 0;
};

struct GeoResult {
    std::string member;
    double score = 0;
    double longitude = 0;
    double latitude = 0;
    double distance_m = 0;
};

// Longitudes, latitudes, radii and box sides all reach redis through getDoubleFromObjectOrReply,
// so they take the same VALUE grammar as a score: "0x10" is 16 degrees, "1e309" is an error, and
// "inf" is a legal radius that simply matches everything. See src/base/numeric.h.
bool parse_double(Slice input, double& value) {
    return parse_double_strict(input, value);
}


bool parse_unit(Slice input, double& meters) {
    if (input.eq_icase("m")) meters = 1.0;
    else if (input.eq_icase("km")) meters = 1000.0;
    else if (input.eq_icase("ft")) meters = 0.3048;
    else if (input.eq_icase("mi")) meters = 1609.34;
    else return false;
    return true;
}

void reply_bad_unit(Op& op) {
    reply_err(op.sink(), "ERR unsupported unit provided. please use M, KM, FT, MI");
}

bool valid_coordinates(double longitude, double latitude) {
    return std::isfinite(longitude) && std::isfinite(latitude) && longitude >= -180.0 &&
           longitude <= 180.0 && latitude >= -kLatitudeMax && latitude <= kLatitudeMax;
}

void reply_invalid_coordinates(Op& op, double longitude, double latitude) {
    // 64 bytes could not hold a large magnitude in FIXED notation (DBL_MAX is 309 integer digits
    // plus '.' plus 6). to_chars then returns value_too_large with ptr == last and leaves the
    // buffer UNSPECIFIED, and appending [begin, ptr) shipped 64 bytes of raw stack to the client:
    // "GEOADD k 1e100 0 m" answered with binary. 344 covers the widest double this can format.
    char lon[344], lat[344];
    auto lon_out = std::to_chars(lon, lon + sizeof(lon), longitude, std::chars_format::fixed, 6);
    auto lat_out = std::to_chars(lat, lat + sizeof(lat), latitude, std::chars_format::fixed, 6);
    if (lon_out.ec != std::errc{}) lon_out.ptr = lon;
    if (lat_out.ec != std::errc{}) lat_out.ptr = lat;
    std::string error = "ERR invalid longitude,latitude pair ";
    error.append(lon, lon_out.ptr);
    error.push_back(',');
    error.append(lat, lat_out.ptr);
    reply_err(op.sink(), error.c_str());
}

uint64_t spread26(uint32_t value) {
    uint64_t result = 0;
    for (int bit = 25; bit >= 0; bit--) result = (result << 2) | ((value >> bit) & 1u);
    return result;
}

uint64_t geo_encode(double longitude, double latitude) {
    const double lon_scaled = (longitude + 180.0) / 360.0 * static_cast<double>(kAxisCells);
    const double lat_scaled = (latitude + kLatitudeMax) / (2.0 * kLatitudeMax) *
                              static_cast<double>(kAxisCells);
    const uint32_t lon = static_cast<uint32_t>(std::min<double>(lon_scaled, kAxisCells - 1));
    const uint32_t lat = static_cast<uint32_t>(std::min<double>(lat_scaled, kAxisCells - 1));
    return (spread26(lon) << 1) | spread26(lat);
}

void geo_decode(double stored_score, double& longitude, double& latitude) {
    const uint64_t hash = static_cast<uint64_t>(stored_score);
    uint32_t lon = 0, lat = 0;
    for (uint32_t bit = 0; bit < 26; bit++) {
        lat |= static_cast<uint32_t>((hash >> (bit * 2)) & 1u) << bit;
        lon |= static_cast<uint32_t>((hash >> (bit * 2 + 1)) & 1u) << bit;
    }
    const double lon_low = -180.0 + static_cast<double>(lon) * 360.0 /
                                      static_cast<double>(kAxisCells);
    const double lon_high = -180.0 + static_cast<double>(lon + 1) * 360.0 /
                                       static_cast<double>(kAxisCells);
    const double lat_low = -kLatitudeMax + static_cast<double>(lat) * (2.0 * kLatitudeMax) /
                                          static_cast<double>(kAxisCells);
    const double lat_high = -kLatitudeMax + static_cast<double>(lat + 1) *
                                           (2.0 * kLatitudeMax) /
                                           static_cast<double>(kAxisCells);
    longitude = (lon_low + lon_high) * 0.5;
    latitude = (lat_low + lat_high) * 0.5;
}

double radians(double degrees) { return degrees * (kPi / 180.0); }

// Faithful Redis 7.4 geohash search cover and predicates (CD5.1).
// Only the shape adapter and interval container are TomoKV-specific. Keep the
// north/south/east/west order: COUNT ANY observes the traversal order.
/*
 * Copyright (c) 2013-2014, yinqiwen <yinqiwen@gmail.com>
 * Copyright (c) 2014, Matt Stancliff <matt@genges.com>.
 * Copyright (c) 2015-current, Redis Ltd.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 *  * Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *  * Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *  * Neither the name of Redis nor the names of its contributors may be used
 *    to endorse or promote products derived from this software without
 *    specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS
 * BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF
 * THE POSSIBILITY OF SUCH DAMAGE.
 */

struct GeoHashRange { double min, max; };
struct GeoHashBits { uint64_t bits; uint8_t step; };
struct GeoHashArea { GeoHashBits hash; GeoHashRange longitude, latitude; };
struct GeoHashNeighbors {
    GeoHashBits north, south, east, west, north_east, north_west, south_east, south_west;
};
struct GeoHashRadius { GeoHashBits hash; GeoHashNeighbors neighbors; GeoHashArea area; };
struct SearchShape {
    bool circular;
    double xy[2];
    struct { double radius; struct { double width, height; } r; } t;
    double conversion, bounds[4];
};
constexpr double MERCATOR_MAX = 20037726.37;
static inline double deg_rad(double ang) { return radians(ang); }
static inline double rad_deg(double ang) { return ang / (kPi / 180.0); }

static inline uint64_t interleave64(uint32_t xlo, uint32_t ylo) {
    static const uint64_t B[] = {0x5555555555555555ULL, 0x3333333333333333ULL,
                                 0x0F0F0F0F0F0F0F0FULL, 0x00FF00FF00FF00FFULL,
                                 0x0000FFFF0000FFFFULL};
    static const unsigned int S[] = {1, 2, 4, 8, 16};

    uint64_t x = xlo;
    uint64_t y = ylo;

    x = (x | (x << S[4])) & B[4];
    y = (y | (y << S[4])) & B[4];

    x = (x | (x << S[3])) & B[3];
    y = (y | (y << S[3])) & B[3];

    x = (x | (x << S[2])) & B[2];
    y = (y | (y << S[2])) & B[2];

    x = (x | (x << S[1])) & B[1];
    y = (y | (y << S[1])) & B[1];

    x = (x | (x << S[0])) & B[0];
    y = (y | (y << S[0])) & B[0];

    return x | (y << 1);
}

static inline uint64_t deinterleave64(uint64_t interleaved) {
    static const uint64_t B[] = {0x5555555555555555ULL, 0x3333333333333333ULL,
                                 0x0F0F0F0F0F0F0F0FULL, 0x00FF00FF00FF00FFULL,
                                 0x0000FFFF0000FFFFULL, 0x00000000FFFFFFFFULL};
    static const unsigned int S[] = {0, 1, 2, 4, 8, 16};

    uint64_t x = interleaved;
    uint64_t y = interleaved >> 1;

    x = (x | (x >> S[0])) & B[0];
    y = (y | (y >> S[0])) & B[0];

    x = (x | (x >> S[1])) & B[1];
    y = (y | (y >> S[1])) & B[1];

    x = (x | (x >> S[2])) & B[2];
    y = (y | (y >> S[2])) & B[2];

    x = (x | (x >> S[3])) & B[3];
    y = (y | (y >> S[3])) & B[3];

    x = (x | (x >> S[4])) & B[4];
    y = (y | (y >> S[4])) & B[4];

    x = (x | (x >> S[5])) & B[5];
    y = (y | (y >> S[5])) & B[5];

    return x | (y << 32);
}

void geohashGetCoordRange(GeoHashRange *long_range, GeoHashRange *lat_range) {
    /* These are constraints from EPSG:900913 / EPSG:3785 / OSGEO:41001 */
    /* We can't geocode at the north/south pole. */
    long_range->max = 180.0;
    long_range->min = -180.0;
    lat_range->max = kLatitudeMax;
    lat_range->min = -kLatitudeMax;
}

int geohashEncode(const GeoHashRange *long_range, const GeoHashRange *lat_range,
                  double longitude, double latitude, uint8_t step,
                  GeoHashBits *hash) {
    /* Check basic arguments sanity. */
    if (hash == NULL || step > 32 || step == 0 ||
        (lat_range->min == 0 && lat_range->max == 0) || (long_range->min == 0 && long_range->max == 0)) return 0;

    /* Return an error when trying to index outside the supported
     * constraints. */
    if (longitude > 180.0 || longitude < -180.0 ||
        latitude > kLatitudeMax || latitude < -kLatitudeMax) return 0;

    hash->bits = 0;
    hash->step = step;

    if (latitude < lat_range->min || latitude > lat_range->max ||
        longitude < long_range->min || longitude > long_range->max) {
        return 0;
    }

    double lat_offset =
        (latitude - lat_range->min) / (lat_range->max - lat_range->min);
    double long_offset =
        (longitude - long_range->min) / (long_range->max - long_range->min);

    /* convert to fixed point based on the step size */
    lat_offset *= (1ULL << step);
    long_offset *= (1ULL << step);
    hash->bits = interleave64(lat_offset, long_offset);
    return 1;
}

int geohashDecode(const GeoHashRange long_range, const GeoHashRange lat_range,
                   const GeoHashBits hash, GeoHashArea *area) {
    if ((hash.bits == 0 && hash.step == 0) || NULL == area || (lat_range.min == 0 && lat_range.max == 0) ||
        (long_range.min == 0 && long_range.max == 0)) {
        return 0;
    }

    area->hash = hash;
    uint8_t step = hash.step;
    uint64_t hash_sep = deinterleave64(hash.bits); /* hash = [LAT][LONG] */

    double lat_scale = lat_range.max - lat_range.min;
    double long_scale = long_range.max - long_range.min;

    uint32_t ilato = hash_sep;       /* get lat part of deinterleaved hash */
    uint32_t ilono = hash_sep >> 32; /* shift over to get long part of hash */

    /* divide by 2**step.
     * Then, for 0-1 coordinate, multiply times scale and add
       to the min to get the absolute coordinate. */
    area->latitude.min =
        lat_range.min + (ilato * 1.0 / (1ull << step)) * lat_scale;
    area->latitude.max =
        lat_range.min + ((ilato + 1) * 1.0 / (1ull << step)) * lat_scale;
    area->longitude.min =
        long_range.min + (ilono * 1.0 / (1ull << step)) * long_scale;
    area->longitude.max =
        long_range.min + ((ilono + 1) * 1.0 / (1ull << step)) * long_scale;

    return 1;
}

static void geohash_move_x(GeoHashBits *hash, int8_t d) {
    if (d == 0)
        return;

    uint64_t x = hash->bits & 0xaaaaaaaaaaaaaaaaULL;
    uint64_t y = hash->bits & 0x5555555555555555ULL;

    uint64_t zz = 0x5555555555555555ULL >> (64 - hash->step * 2);

    if (d > 0) {
        x = x + (zz + 1);
    } else {
        x = x | zz;
        x = x - (zz + 1);
    }

    x &= (0xaaaaaaaaaaaaaaaaULL >> (64 - hash->step * 2));
    hash->bits = (x | y);
}

static void geohash_move_y(GeoHashBits *hash, int8_t d) {
    if (d == 0)
        return;

    uint64_t x = hash->bits & 0xaaaaaaaaaaaaaaaaULL;
    uint64_t y = hash->bits & 0x5555555555555555ULL;

    uint64_t zz = 0xaaaaaaaaaaaaaaaaULL >> (64 - hash->step * 2);
    if (d > 0) {
        y = y + (zz + 1);
    } else {
        y = y | zz;
        y = y - (zz + 1);
    }
    y &= (0x5555555555555555ULL >> (64 - hash->step * 2));
    hash->bits = (x | y);
}

void geohashNeighbors(const GeoHashBits *hash, GeoHashNeighbors *neighbors) {
    neighbors->east = *hash;
    neighbors->west = *hash;
    neighbors->north = *hash;
    neighbors->south = *hash;
    neighbors->south_east = *hash;
    neighbors->south_west = *hash;
    neighbors->north_east = *hash;
    neighbors->north_west = *hash;

    geohash_move_x(&neighbors->east, 1);
    geohash_move_y(&neighbors->east, 0);

    geohash_move_x(&neighbors->west, -1);
    geohash_move_y(&neighbors->west, 0);

    geohash_move_x(&neighbors->south, 0);
    geohash_move_y(&neighbors->south, -1);

    geohash_move_x(&neighbors->north, 0);
    geohash_move_y(&neighbors->north, 1);

    geohash_move_x(&neighbors->north_west, -1);
    geohash_move_y(&neighbors->north_west, 1);

    geohash_move_x(&neighbors->north_east, 1);
    geohash_move_y(&neighbors->north_east, 1);

    geohash_move_x(&neighbors->south_east, 1);
    geohash_move_y(&neighbors->south_east, -1);

    geohash_move_x(&neighbors->south_west, -1);
    geohash_move_y(&neighbors->south_west, -1);
}

uint8_t geohashEstimateStepsByRadius(double range_meters, double lat) {
    if (range_meters == 0) return 26;
    int step = 1;
    while (range_meters < MERCATOR_MAX) {
        range_meters *= 2;
        step++;
    }
    step -= 2; /* Make sure range is included in most of the base cases. */

    /* Wider range towards the poles... Note: it is possible to do better
     * than this approximation by computing the distance between meridians
     * at this latitude, but this does the trick for now. */
    if (lat > 66 || lat < -66) {
        step--;
        if (lat > 80 || lat < -80) step--;
    }

    /* Frame to valid range. */
    if (step < 1) step = 1;
    if (step > 26) step = 26;
    return step;
}

int geohashBoundingBox(SearchShape *shape, double *bounds) {
    if (!bounds) return 0;
    double longitude = shape->xy[0];
    double latitude = shape->xy[1];
    double height = shape->conversion * (shape->circular ? shape->t.radius : shape->t.r.height/2);
    double width = shape->conversion * (shape->circular ? shape->t.radius : shape->t.r.width/2);

    const double lat_delta = rad_deg(height/kEarthRadiusMeters);
    const double long_delta_top = rad_deg(width/kEarthRadiusMeters/cos(deg_rad(latitude+lat_delta)));
    const double long_delta_bottom = rad_deg(width/kEarthRadiusMeters/cos(deg_rad(latitude-lat_delta)));
    /* The directions of the northern and southern hemispheres
     * are opposite, so we choice different points as min/max long/lat */
    int southern_hemisphere = latitude < 0 ? 1 : 0;
    bounds[0] = southern_hemisphere ? longitude-long_delta_bottom : longitude-long_delta_top;
    bounds[2] = southern_hemisphere ? longitude+long_delta_bottom : longitude+long_delta_top;
    bounds[1] = latitude - lat_delta;
    bounds[3] = latitude + lat_delta;
    return 1;
}

GeoHashRadius geohashCalculateAreasByShapeWGS84(SearchShape *shape) {
    GeoHashRange long_range, lat_range;
    GeoHashRadius radius;
    GeoHashBits hash;
    GeoHashNeighbors neighbors;
    GeoHashArea area;
    double min_lon, max_lon, min_lat, max_lat;
    int steps;

    geohashBoundingBox(shape, shape->bounds);
    min_lon = shape->bounds[0];
    min_lat = shape->bounds[1];
    max_lon = shape->bounds[2];
    max_lat = shape->bounds[3];

    double longitude = shape->xy[0];
    double latitude = shape->xy[1];
    /* radius_meters is calculated differently in different search types:
     * 1) CIRCULAR_TYPE, just use radius.
     * 2) RECTANGLE_TYPE, we use sqrt((width/2)^2 + (height/2)^2) to
     * calculate the distance from the center point to the corner */
    double radius_meters = shape->circular ? shape->t.radius :
            sqrt((shape->t.r.width/2)*(shape->t.r.width/2) + (shape->t.r.height/2)*(shape->t.r.height/2));
    radius_meters *= shape->conversion;

    steps = geohashEstimateStepsByRadius(radius_meters,latitude);

    geohashGetCoordRange(&long_range,&lat_range);
    geohashEncode(&long_range,&lat_range,longitude,latitude,steps,&hash);
    geohashNeighbors(&hash,&neighbors);
    geohashDecode(long_range,lat_range,hash,&area);

    /* Check if the step is enough at the limits of the covered area.
     * Sometimes when the search area is near an edge of the
     * area, the estimated step is not small enough, since one of the
     * north / south / west / east square is too near to the search area
     * to cover everything. */
    int decrease_step = 0;
    {
        GeoHashArea north, south, east, west;

        geohashDecode(long_range, lat_range, neighbors.north, &north);
        geohashDecode(long_range, lat_range, neighbors.south, &south);
        geohashDecode(long_range, lat_range, neighbors.east, &east);
        geohashDecode(long_range, lat_range, neighbors.west, &west);

        if (north.latitude.max < max_lat) 
            decrease_step = 1;
        if (south.latitude.min > min_lat) 
            decrease_step = 1;
        if (east.longitude.max < max_lon) 
            decrease_step = 1;
        if (west.longitude.min > min_lon)  
            decrease_step = 1;
    }

    if (steps > 1 && decrease_step) {
        steps--;
        geohashEncode(&long_range,&lat_range,longitude,latitude,steps,&hash);
        geohashNeighbors(&hash,&neighbors);
        geohashDecode(long_range,lat_range,hash,&area);
    }

    /* Exclude the search areas that are useless. */
    if (steps >= 2) {
        if (area.latitude.min < min_lat) {
            neighbors.south = {};
            neighbors.south_west = {};
            neighbors.south_east = {};
        }
        if (area.latitude.max > max_lat) {
            neighbors.north = {};
            neighbors.north_east = {};
            neighbors.north_west = {};
        }
        if (area.longitude.min < min_lon) {
            neighbors.west = {};
            neighbors.south_west = {};
            neighbors.north_west = {};
        }
        if (area.longitude.max > max_lon) {
            neighbors.east = {};
            neighbors.south_east = {};
            neighbors.north_east = {};
        }
    }
    radius.hash = hash;
    radius.neighbors = neighbors;
    radius.area = area;
    return radius;
}

double geohashGetLatDistance(double lat1d, double lat2d) {
    return kEarthRadiusMeters * fabs(deg_rad(lat2d) - deg_rad(lat1d));
}

__attribute__((optimize("fp-contract=off")))
double geohashGetDistance(double lon1d, double lat1d, double lon2d, double lat2d) {
    double lat1r, lon1r, lat2r, lon2r, u, v, a;
    lon1r = deg_rad(lon1d);
    lon2r = deg_rad(lon2d);
    v = sin((lon2r - lon1r) / 2);
    /* if v == 0 we can avoid doing expensive math when lons are practically the same */
    if (v == 0.0)
        return geohashGetLatDistance(lat1d, lat2d);
    lat1r = deg_rad(lat1d);
    lat2r = deg_rad(lat2d);
    u = sin((lat2r - lat1r) / 2);
    a = u * u + cos(lat1r) * cos(lat2r) * v * v;
    return 2.0 * kEarthRadiusMeters * asin(sqrt(a));
}

int geohashGetDistanceIfInRadius(double x1, double y1,
                                 double x2, double y2, double radius,
                                 double *distance) {
    *distance = geohashGetDistance(x1, y1, x2, y2);
    if (*distance > radius) return 0;
    return 1;
}

int geohashGetDistanceIfInRectangle(double width_m, double height_m, double x1, double y1,
                                    double x2, double y2, double *distance) {
    /* latitude distance is less expensive to compute than longitude distance
     * so we check first for the latitude condition */
    double lat_distance = geohashGetLatDistance(y2, y1);
    if (lat_distance > height_m/2) {
        return 0;
    }
    double lon_distance = geohashGetDistance(x2, y2, x1, y2);
    if (lon_distance > width_m/2) {
        return 0;
    }
    *distance = geohashGetDistance(x1, y1, x2, y2);
    return 1;
}

double geo_distance(double lon1, double lat1, double lon2, double lat2) {
    return geohashGetDistance(lon1, lat1, lon2, lat2);
}

struct ScoreInterval { uint64_t first, last; }; // last is exclusive

std::vector<ScoreInterval> geo_neighbor_intervals(const GeoSearchOptions& options,
                                                  double longitude, double latitude) {
    SearchShape shape{};
    shape.circular = options.shape == GeoShape::Radius;
    shape.xy[0] = longitude; shape.xy[1] = latitude;
    shape.conversion = 1;
    shape.t.radius = options.radius_m;
    shape.t.r.width = options.width_m; shape.t.r.height = options.height_m;
    const GeoHashRadius cover = geohashCalculateAreasByShapeWGS84(&shape);
    const GeoHashBits neighbors[] = {cover.hash, cover.neighbors.north, cover.neighbors.south,
        cover.neighbors.east, cover.neighbors.west, cover.neighbors.north_east,
        cover.neighbors.north_west, cover.neighbors.south_east, cover.neighbors.south_west};
    std::vector<ScoreInterval> intervals;
    intervals.reserve(9);
    unsigned last_processed = 0;
    for (unsigned i = 0; i < 9; ++i) {
        const auto hash = neighbors[i];
        if (!hash.bits && !hash.step) continue;
        if (last_processed && hash.bits == neighbors[last_processed].bits &&
            hash.step == neighbors[last_processed].step) continue;
        const unsigned shift = 52 - hash.step * 2;
        intervals.push_back({hash.bits << shift, (hash.bits + 1) << shift});
        last_processed = i;
    }
    return intervals;
}

// Validation runs only after the source lookup (including for STORE's gathered image).
// Redis resolves members while walking options, so a later malformed shape cannot mask it.
bool parse_search(Op& op, GeoSearchOptions& options, const std::vector<ZsetEntry>& source) {
    const bool search_store = op.cmd_name().eq_icase("geosearchstore");
    const bool search = op.cmd_name().eq_icase("geosearch") || search_store;
    const bool by_member = op.cmd_name().eq_icase("georadiusbymember") ||
                           op.cmd_name().eq_icase("georadiusbymember_ro");
    const bool read_only_radius = op.cmd_name().eq_icase("georadius_ro") ||
                                  op.cmd_name().eq_icase("georadiusbymember_ro");
    options = {};
    options.source_arg = search_store ? 2 : 1;
    options.store = search_store;
    options.destination_arg = search_store ? 1 : 0;
    auto coordinates = [&](uint32_t arg) {
        if (!parse_double(op.arg(arg), options.longitude) ||
            !parse_double(op.arg(arg + 1), options.latitude)) {
            reply_err(op.sink(), "ERR value is not a valid float"); return false;
        }
        if (!valid_coordinates(options.longitude, options.latitude)) {
            reply_invalid_coordinates(op, options.longitude, options.latitude); return false;
        }
        return true;
    };
    auto member = [&](uint32_t arg) {
        if (source.empty()) return true;
        const Slice name = op.arg(arg);
        auto it = std::find_if(source.begin(), source.end(), [&](const ZsetEntry& e) {
            return Slice(e.member.data(), e.member.size()) == name;
        });
        if (it == source.end() || !std::isfinite(it->score) || it->score < 0 ||
            it->score >= static_cast<double>(uint64_t{1} << 52)) {
            reply_err(op.sink(), "ERR could not decode requested zset member"); return false;
        }
        geo_decode(it->score, options.longitude, options.latitude);
        return true;
    };
    auto radius = [&](uint32_t arg) {
        if (!parse_double(op.arg(arg), options.radius_m)) {
            reply_err(op.sink(), "ERR need numeric radius"); return false;
        }
        if (options.radius_m < 0) {
            reply_err(op.sink(), "ERR radius cannot be negative"); return false;
        }
        if (!parse_unit(op.arg(arg + 1), options.unit_m)) { reply_bad_unit(op); return false; }
        options.radius_m *= options.unit_m;
        options.shape = GeoShape::Radius;
        return true;
    };
    uint32_t arg = search_store ? 3 : 2;
    if (!search) {
        arg = by_member ? 5 : 6;
        if (by_member) {
            if (!source.empty() && (!member(2) || !radius(3))) return false;
        } else if (!coordinates(2) || !radius(4)) return false;
    }
    bool frommember = false, fromloc = false, byradius = false, bybox = false;
    for (; arg < op.argc(); arg++) {
        const Slice token = op.arg(arg);
        if (token.eq_icase("asc")) options.order = GeoOrder::Asc;
        else if (token.eq_icase("desc")) options.order = GeoOrder::Desc;
        else if (token.eq_icase("withcoord")) options.with_coord = true;
        else if (token.eq_icase("withdist")) options.with_dist = true;
        else if (token.eq_icase("withhash")) options.with_hash = true;
        else if (token.eq_icase("any")) options.any = true;
        else if (token.eq_icase("count") && arg + 1 < op.argc()) {
            int64_t count = 0;
            const Slice number = op.arg(++arg);
            const auto parsed = std::from_chars(number.p, number.p + number.n, count);
            const std::string canonical = std::to_string(count);
            if (parsed.ec != std::errc{} || parsed.ptr != number.p + number.n ||
                Slice(canonical.data(), canonical.size()) != number) {
                reply_err(op.sink(), "ERR value is not an integer or out of range"); return false;
            }
            if (count <= 0) { reply_err(op.sink(), "ERR COUNT must be > 0"); return false; }
            options.count = static_cast<uint64_t>(count);
        } else if (!search && !read_only_radius && arg + 1 < op.argc() &&
                   (token.eq_icase("store") || token.eq_icase("storedist"))) {
            options.destination_arg = ++arg;
            options.store = true;
            options.store_distance = token.eq_icase("storedist");
        } else if (search_store && token.eq_icase("storedist")) options.store_distance = true;
        else if (search && !fromloc && token.eq_icase("frommember") && arg + 1 < op.argc()) {
            if (!member(++arg)) return false;
            frommember = true;
        } else if (search && !frommember && token.eq_icase("fromlonlat") && arg + 2 < op.argc()) {
            if (!coordinates(arg + 1)) return false;
            arg += 2; fromloc = true;
        } else if (search && !bybox && token.eq_icase("byradius") && arg + 2 < op.argc()) {
            if (!radius(arg + 1)) return false;
            arg += 2; byradius = true;
        } else if (search && !byradius && token.eq_icase("bybox") && arg + 3 < op.argc()) {
            if (!parse_double(op.arg(arg + 1), options.width_m)) {
                reply_err(op.sink(), "ERR need numeric width"); return false;
            }
            if (!parse_double(op.arg(arg + 2), options.height_m)) {
                reply_err(op.sink(), "ERR need numeric height"); return false;
            }
            if (options.width_m < 0 || options.height_m < 0) {
                reply_err(op.sink(), "ERR height or width cannot be negative"); return false;
            }
            if (!parse_unit(op.arg(arg + 3), options.unit_m)) { reply_bad_unit(op); return false; }
            options.width_m *= options.unit_m;
            options.height_m *= options.unit_m;
            options.shape = GeoShape::Box;
            arg += 3; bybox = true;
        } else { reply_syntax(op.sink()); return false; }
    }
    if (options.store && (options.with_coord || options.with_dist || options.with_hash)) {
        reply_err(op.sink(), search_store
            ? "ERR GEOSEARCHSTORE is not compatible with WITHDIST, WITHHASH and WITHCOORD options"
            : "ERR STORE option in GEORADIUS is not compatible with WITHDIST, WITHHASH and WITHCOORD options");
        return false;
    }
    const char* missing = search && !frommember && !fromloc
        ? "ERR exactly one of FROMMEMBER or FROMLONLAT can be specified for "
        : search && !byradius && !bybox
        ? "ERR exactly one of BYRADIUS and BYBOX can be specified for " : nullptr;
    if (missing) {
        std::string error(missing);
        error.append(op.cmd_name().p, op.cmd_name().n);
        reply_err(op.sink(), error.c_str()); return false;
    }
    if (options.any && !options.count) {
        reply_err(op.sink(), "ERR the ANY argument requires COUNT argument"); return false;
    }
    if (options.count && options.order == GeoOrder::None && !options.any)
        options.order = GeoOrder::Asc;
    return true;
}

GeoBuildResult run_search(const GeoSearchOptions& options,
                          const std::vector<ZsetEntry>& source,
                          std::vector<GeoResult>& output) {
    output.clear();
    if (source.empty()) return GeoBuildResult::Ok;
    double center_lon = options.longitude;
    double center_lat = options.latitude;
    if (options.from_member) {
        auto found = std::find_if(source.begin(), source.end(), [&](const ZsetEntry& entry) {
            return entry.member.size() == options.member.n &&
                   (!options.member.n || !std::memcmp(entry.member.data(), options.member.p,
                                                       options.member.n));
        });
        if (found == source.end()) return GeoBuildResult::MissingMember;
        geo_decode(found->score, center_lon, center_lat);
    }
    try {
        const std::vector<ScoreInterval> intervals =
            geo_neighbor_intervals(options, center_lon, center_lat);
        output.reserve(source.size());
        bool early = false;
        for (const ScoreInterval& interval : intervals) {
            auto entry = std::lower_bound(source.begin(), source.end(), interval.first,
                [](const ZsetEntry& item, uint64_t score) {
                    return static_cast<uint64_t>(item.score) < score;
                });
            for (; entry != source.end() &&
                   static_cast<uint64_t>(entry->score) < interval.last; ++entry) {
                double longitude = 0, latitude = 0;
                geo_decode(entry->score, longitude, latitude);
                double distance = 0;
                const bool inside = options.shape == GeoShape::Radius
                    ? geohashGetDistanceIfInRadius(center_lon, center_lat, longitude, latitude,
                                                   options.radius_m, &distance)
                    : geohashGetDistanceIfInRectangle(options.width_m, options.height_m,
                        center_lon, center_lat, longitude, latitude, &distance);
                if (inside)
                    output.push_back({entry->member, entry->score, longitude, latitude, distance});
                if (options.any && options.count && output.size() >= options.count) {
                    early = true;
                    break;
                }
            }
            if (early) break;
        }
        if (options.order != GeoOrder::None) {
            std::sort(output.begin(), output.end(), [&](const GeoResult& a, const GeoResult& b) {
                if (a.distance_m != b.distance_m)
                    return options.order == GeoOrder::Desc ? a.distance_m > b.distance_m
                                                           : a.distance_m < b.distance_m;
                return a.score < b.score;
            });
        }
        if (options.count && output.size() > options.count)
            output.resize(static_cast<size_t>(options.count));
    } catch (const std::bad_alloc&) {
        output.clear();
        return GeoBuildResult::Oom;
    }
    return GeoBuildResult::Ok;
}

void reply_fixed_bulk(Op& op, double value, int precision) {
    char text[96];
    auto out = std::to_chars(text, text + sizeof(text), value, std::chars_format::fixed, precision);
    reply_bulk(op.sink(), Slice(text, static_cast<uint32_t>(out.ptr - text)));
}

void reply_coordinate(Op& op, double value) {
    char text[96];
    const int size = std::snprintf(text, sizeof(text), "%.17Lf", static_cast<long double>(value));
    // Redis LD_STR_HUMAN: fixed 17 fractional digits, then trim zeroes and the dot.
    // Coordinates are finite and bounded, so the fixed conversion always fits this buffer.
    char* end = text + size;
    while (end[-1] == '0') --end;
    if (end[-1] == '.') --end;
    if (end == text + 2 && text[0] == '-' && text[1] == '0') {
        text[0] = '0';
        end = text + 1;
    }
    const uint32_t length = static_cast<uint32_t>(end - text);
    if (!op.resp3()) {
        reply_bulk(op.sink(), Slice(text, length));
        return;
    }
    auto&& sink = op.sink();
    char* frame = sink.reserve(static_cast<size_t>(length) + 3);
    *frame = ',';
    std::memcpy(frame + 1, text, length);
    frame[length + 1] = '\r';
    frame[length + 2] = '\n';
    sink.advance(static_cast<size_t>(length) + 3);
}

void reply_geo_results(Op& op, const GeoSearchOptions& options,
                       const std::vector<GeoResult>& results) {
    reply_array_header(op.sink(), results.size());
    const bool details = options.with_coord || options.with_dist || options.with_hash;
    for (const GeoResult& result : results) {
        if (details) reply_array_header(op.sink(), 1 + options.with_dist + options.with_hash +
                                                   options.with_coord);
        reply_bulk(op.sink(), Slice(result.member.data(), static_cast<uint32_t>(result.member.size())));
        if (options.with_dist) reply_fixed_bulk(op, result.distance_m / options.unit_m, 4);
        if (options.with_hash) reply_int(op.sink(), static_cast<long long>(result.score));
        if (options.with_coord) {
            reply_array_header(op.sink(), 2);
            reply_coordinate(op, result.longitude);
            reply_coordinate(op, result.latitude);
        }
    }
}

void reply_owner_error(Op& op, ZsetOwnerResult result) {
    if (result == ZsetOwnerResult::WrongType) reply_wrongtype(op.sink());
    else if (result == ZsetOwnerResult::Maxmemory) reply_maxmemory_oom(op);
    else if (result == ZsetOwnerResult::InsertFailed)
        reply_err(op.sink(), "ERR keyspace insert failed");
    else reply_err(op.sink(), "ERR out of memory");
}

template <bool kNotify>
void cmd_geoadd(Shard& shard, Op& op) {
    bool nx = false, xx = false, ch = false;
    uint32_t arg = 2;
    while (arg < op.argc()) {
        if (op.arg(arg).eq_icase("nx")) nx = true;
        else if (op.arg(arg).eq_icase("xx")) xx = true;
        else if (op.arg(arg).eq_icase("ch")) ch = true;
        else break;
        arg++;
    }
    if (nx && xx) { reply_syntax(op.sink()); return; }
    if (arg == op.argc() || (op.argc() - arg) % 3) { reply_syntax(op.sink()); return; }

    struct Addition { double longitude, latitude; Slice member; uint64_t score; };
    std::vector<Addition> additions;
    try { additions.reserve((op.argc() - arg) / 3); }
    catch (const std::bad_alloc&) { reply_err(op.sink(), "ERR out of memory"); return; }
    for (; arg < op.argc(); arg += 3) {
        double longitude = 0, latitude = 0;
        if (!parse_double(op.arg(arg), longitude) || !parse_double(op.arg(arg + 1), latitude)) {
            reply_err(op.sink(), "ERR value is not a valid float"); return;
        }
        if (!valid_coordinates(longitude, latitude)) {
            reply_invalid_coordinates(op, longitude, latitude); return;
        }
        additions.push_back({longitude, latitude, op.arg(arg + 2), geo_encode(longitude, latitude)});
    }

    std::vector<ZsetEntry> entries;
    int64_t expire_at_ms = -1;
    bool reserve_ttl_slot = false;
    const ZsetOwnerResult read = zset_owner_read(shard, op.key(), op.hash, kNotify, false,
                                                 entries, expire_at_ms, &reserve_ttl_slot);
    if (read != ZsetOwnerResult::Ok && read != ZsetOwnerResult::Missing) {
        reply_owner_error(op, read); return;
    }
    uint64_t added = 0, changed = 0;
    try {
        for (const Addition& addition : additions) {
            auto found = std::find_if(entries.begin(), entries.end(), [&](const ZsetEntry& entry) {
                return entry.member.size() == addition.member.n &&
                       (!addition.member.n || !std::memcmp(entry.member.data(), addition.member.p,
                                                            addition.member.n));
            });
            if (found == entries.end()) {
                if (xx) continue;
                entries.push_back({std::string(addition.member.p, addition.member.n),
                                   static_cast<double>(addition.score)});
                added++;
            } else if (!nx && found->score != static_cast<double>(addition.score)) {
                found->score = static_cast<double>(addition.score);
                changed++;
            }
        }
        std::sort(entries.begin(), entries.end(), [](const ZsetEntry& a, const ZsetEntry& b) {
            if (a.score != b.score) return a.score < b.score;
            return a.member < b.member;
        });
    } catch (const std::bad_alloc&) { reply_err(op.sink(), "ERR out of memory"); return; }
    if (added || changed) {
        // GEOADD is an in-place ZADD in Redis: retain the touched key's eviction history and
        // never demote its encoding. The owner read above already removed an expired key.
        KvObj* previous = shard.store().find_resident(op.hash, op.key());
        const uint8_t eviction_meta = previous ? previous->eviction_meta() : 0;
        const bool expanded = previous &&
            CollectionRef(previous).encoding() != CollectionEncoding::Compact;
        const ZsetOwnerResult stored = zset_owner_replace(shard, op.key(), op.hash, kNotify,
                                                          entries, expire_at_ms,
                                                          eviction_meta, expanded,
                                                          reserve_ttl_slot);
        if (stored != ZsetOwnerResult::Ok) { reply_owner_error(op, stored); return; }
        if constexpr (kNotify)
            notify_record(shard, op, NOTIFY_ZSET, NotifyEventId::Zadd, op.key());
        if (shard.has_blocking_waiters()) blocking_publish_zset_op(shard, op);
    }
    reply_int(op.sink(), static_cast<long long>(ch ? added + changed : added));
}

template <bool kNotify>
void cmd_geopos(Shard& shard, Op& op) {
    std::vector<ZsetEntry> entries;
    int64_t expire = -1;
    const ZsetOwnerResult read = zset_owner_read(
        shard, op.key(), op.hash, kNotify, true, entries, expire);
    if (read == ZsetOwnerResult::WrongType) { reply_wrongtype(op.sink()); return; }
    if (read != ZsetOwnerResult::Ok && read != ZsetOwnerResult::Missing) {
        reply_owner_error(op, read); return;
    }
    reply_array_header(op.sink(), op.argc() - 2);
    for (uint32_t arg = 2; arg < op.argc(); arg++) {
        auto found = std::find_if(entries.begin(), entries.end(), [&](const ZsetEntry& entry) {
            return entry.member.size() == op.arg(arg).n &&
                   (!op.arg(arg).n || !std::memcmp(entry.member.data(), op.arg(arg).p, op.arg(arg).n));
        });
        if (found == entries.end()) { reply_null_array(op.sink(), op.resp3()); continue; }
        double longitude = 0, latitude = 0;
        geo_decode(found->score, longitude, latitude);
        reply_array_header(op.sink(), 2);
        reply_coordinate(op, longitude);
        reply_coordinate(op, latitude);
    }
}

template <bool kNotify>
void cmd_geohash(Shard& shard, Op& op) {
    std::vector<ZsetEntry> entries;
    int64_t expire = -1;
    const ZsetOwnerResult read = zset_owner_read(
        shard, op.key(), op.hash, kNotify, true, entries, expire);
    if (read == ZsetOwnerResult::WrongType) { reply_wrongtype(op.sink()); return; }
    if (read != ZsetOwnerResult::Ok && read != ZsetOwnerResult::Missing) {
        reply_owner_error(op, read); return;
    }
    static constexpr char alphabet[] = "0123456789bcdefghjkmnpqrstuvwxyz";
    reply_array_header(op.sink(), op.argc() - 2);
    for (uint32_t arg = 2; arg < op.argc(); arg++) {
        auto found = std::find_if(entries.begin(), entries.end(), [&](const ZsetEntry& entry) {
            return entry.member.size() == op.arg(arg).n &&
                   (!op.arg(arg).n || !std::memcmp(entry.member.data(), op.arg(arg).p, op.arg(arg).n));
        });
        if (found == entries.end()) { reply_null(op.sink(), op.resp3()); continue; }
        double longitude = 0, latitude = 0;
        geo_decode(found->score, longitude, latitude);
        char hash[11];
        double lon_min = -180, lon_max = 180, lat_min = -90, lat_max = 90;
        for (uint32_t character = 0; character < 10; character++) {
            uint8_t value = 0;
            for (uint32_t bit = 0; bit < 5; bit++) {
                const bool longitude_bit = ((character * 5 + bit) & 1u) == 0;
                bool high = false;
                if (longitude_bit) {
                    const double mid = (lon_min + lon_max) * 0.5;
                    high = longitude >= mid;
                    if (high) lon_min = mid; else lon_max = mid;
                } else {
                    const double mid = (lat_min + lat_max) * 0.5;
                    high = latitude >= mid;
                    if (high) lat_min = mid; else lat_max = mid;
                }
                value = static_cast<uint8_t>((value << 1) | high);
            }
            hash[character] = alphabet[value];
        }
        hash[10] = '0';
        reply_bulk(op.sink(), Slice(hash, sizeof(hash)));
    }
}

template <bool kNotify>
void cmd_geodist(Shard& shard, Op& op) {
    double unit_m = 1;
    if (op.argc() == 5 && !parse_unit(op.arg(4), unit_m)) { reply_bad_unit(op); return; }
    std::vector<ZsetEntry> entries;
    int64_t expire = -1;
    const ZsetOwnerResult read = zset_owner_read(
        shard, op.key(), op.hash, kNotify, true, entries, expire);
    if (read == ZsetOwnerResult::WrongType) { reply_wrongtype(op.sink()); return; }
    if (read != ZsetOwnerResult::Ok && read != ZsetOwnerResult::Missing) {
        reply_owner_error(op, read); return;
    }
    auto find = [&](Slice member) -> const ZsetEntry* {
        auto it = std::find_if(entries.begin(), entries.end(), [&](const ZsetEntry& entry) {
            return entry.member.size() == member.n &&
                   (!member.n || !std::memcmp(entry.member.data(), member.p, member.n));
        });
        return it == entries.end() ? nullptr : &*it;
    };
    const ZsetEntry* first = find(op.arg(2));
    const ZsetEntry* second = find(op.arg(3));
    if (!first || !second) { reply_null(op.sink(), op.resp3()); return; }
    double lon1, lat1, lon2, lat2;
    geo_decode(first->score, lon1, lat1);
    geo_decode(second->score, lon2, lat2);
    reply_fixed_bulk(op, geo_distance(lon1, lat1, lon2, lat2) / unit_m, 4);
}

template <bool kNotify>
void cmd_geosearch(Shard& shard, Op& op) {
    GeoSearchOptions options;
    std::vector<ZsetEntry> entries;
    int64_t expire = -1;
    const Slice key = op.arg(op.cmd_name().eq_icase("geosearchstore") ? 2 : 1);
    const uint64_t hash = FlatStore::hash_key(key);
    const ZsetOwnerResult read = zset_owner_read(
        shard, key, hash, kNotify, true, entries, expire);
    if (read == ZsetOwnerResult::WrongType) { reply_wrongtype(op.sink()); return; }
    if (read != ZsetOwnerResult::Ok && read != ZsetOwnerResult::Missing) {
        reply_owner_error(op, read); return;
    }
    if (!parse_search(op, options, entries)) return;
    std::vector<GeoResult> results;
    const GeoBuildResult built = run_search(options, entries, results);
    if (built == GeoBuildResult::MissingMember) {
        reply_err(op.sink(), "ERR could not decode requested zset member"); return;
    }
    if (built == GeoBuildResult::Oom) { reply_err(op.sink(), "ERR out of memory"); return; }
    reply_geo_results(op, options, results);
}

void cmd_geoadd_clean(Shard& shard, Op& op) { cmd_geoadd<false>(shard, op); }
void cmd_geoadd_armed(Shard& shard, Op& op) { cmd_geoadd<true>(shard, op); }
void cmd_geopos_clean(Shard& shard, Op& op) { cmd_geopos<false>(shard, op); }
void cmd_geopos_armed(Shard& shard, Op& op) { cmd_geopos<true>(shard, op); }
void cmd_geohash_clean(Shard& shard, Op& op) { cmd_geohash<false>(shard, op); }
void cmd_geohash_armed(Shard& shard, Op& op) { cmd_geohash<true>(shard, op); }
void cmd_geodist_clean(Shard& shard, Op& op) { cmd_geodist<false>(shard, op); }
void cmd_geodist_armed(Shard& shard, Op& op) { cmd_geodist<true>(shard, op); }
void cmd_geosearch_clean(Shard& shard, Op& op) { cmd_geosearch<false>(shard, op); }
void cmd_geosearch_armed(Shard& shard, Op& op) { cmd_geosearch<true>(shard, op); }

static const CommandSpec kTable[] = {
    {"GEOADD", 5, -1, CmdFlags::Write | CmdFlags::DenyOom,
     cmd_geoadd_clean, 1, 1, 1, notify_handler<cmd_geoadd_armed>},
    // Minimum 2 for the member-list readers: redis answers "GEOPOS key" with an empty array.
    {"GEOPOS", 2, -1, CmdFlags::Readonly,
     cmd_geopos_clean, 1, 1, 1, notify_handler<cmd_geopos_armed>},
    {"GEODIST", 4, 5, CmdFlags::Readonly,
     cmd_geodist_clean, 1, 1, 1, notify_handler<cmd_geodist_armed>},
    {"GEOHASH", 2, -1, CmdFlags::Readonly,
     cmd_geohash_clean, 1, 1, 1, notify_handler<cmd_geohash_armed>},
    {"GEOSEARCH", 7, -1, CmdFlags::Readonly,
     cmd_geosearch_clean, 1, 1, 1, notify_handler<cmd_geosearch_armed>},
    {"GEOSEARCHSTORE", 8, -1, CmdFlags::Write | CmdFlags::DenyOom | CmdFlags::MultiShard,
     cmd_xshard_only, 1, 2, 1},
    {"GEORADIUS", 6, -1, CmdFlags::Write | CmdFlags::DenyOom | CmdFlags::MultiShard,
     cmd_xshard_only, 1, -1, 1},
    {"GEORADIUSBYMEMBER", 5, -1, CmdFlags::Write | CmdFlags::DenyOom | CmdFlags::MultiShard,
     cmd_xshard_only, 1, -1, 1},
    {"GEORADIUS_RO", 6, -1, CmdFlags::Readonly | CmdFlags::MultiShard,
     cmd_xshard_only, 1, 1, 1},
    {"GEORADIUSBYMEMBER_RO", 5, -1, CmdFlags::Readonly | CmdFlags::MultiShard,
     cmd_xshard_only, 1, 1, 1},
};

}  // namespace

bool geo_prepare_route(Op& op, GeoRoute& route) {
    // Key extraction must not validate before the source owner's type/member lookup.
    route = {};
    if (op.cmd_name().eq_icase("geosearchstore")) {
        route.store = true; route.source_arg = 2; route.destination_arg = 1;
    } else if (op.cmd_name().eq_icase("georadius") ||
               op.cmd_name().eq_icase("georadiusbymember")) {
        uint32_t arg = op.cmd_name().eq_icase("georadius") ? 6 : 5;
        for (; arg < op.argc(); ++arg) {
            const Slice token = op.arg(arg);
            if (token.eq_icase("count") && arg + 1 < op.argc()) ++arg;
            else if ((token.eq_icase("store") || token.eq_icase("storedist")) && arg + 1 < op.argc()) {
                route.store = true;
                route.store_distance = token.eq_icase("storedist");
                route.destination_arg = ++arg;
            }
        }
    }
    return true;
}

GeoBuildResult geo_build_store(Op& op, const std::vector<ZsetEntry>& source,
                               std::vector<ZsetEntry>& destination) {
    GeoSearchOptions options;
    if (!parse_search(op, options, source)) return GeoBuildResult::Invalid;
    std::vector<GeoResult> results;
    const GeoBuildResult built = run_search(options, source, results);
    if (built != GeoBuildResult::Ok) return built;
    destination.clear();
    try {
        destination.reserve(results.size());
        for (GeoResult& result : results)
            destination.push_back({std::move(result.member), options.store_distance
                ? result.distance_m / options.unit_m : result.score});
        std::sort(destination.begin(), destination.end(), [](const ZsetEntry& a, const ZsetEntry& b) {
            if (a.score != b.score) return a.score < b.score;
            return a.member < b.member;
        });
    } catch (const std::bad_alloc&) {
        destination.clear();
        return GeoBuildResult::Oom;
    }
    return GeoBuildResult::Ok;
}

void cmd_geo_xshard_local(Shard& shard, Op& op, bool notify) {
    GeoRoute options;
    geo_prepare_route(op, options);
    if (!options.store) {
        if (notify) cmd_geosearch<true>(shard, op);
        else cmd_geosearch<false>(shard, op);
        return;
    }
    const Slice source_key = op.arg(options.source_arg);
    const uint64_t source_hash = FlatStore::hash_key(source_key);
    std::vector<ZsetEntry> source;
    int64_t expire = -1;
    const ZsetOwnerResult read = zset_owner_read(shard, source_key, source_hash, notify, true,
                                                 source, expire);
    if (read == ZsetOwnerResult::WrongType) { reply_wrongtype(op.sink()); return; }
    if (read != ZsetOwnerResult::Ok && read != ZsetOwnerResult::Missing) {
        reply_owner_error(op, read); return;
    }
    std::vector<ZsetEntry> output;
    const GeoBuildResult built = geo_build_store(op, source, output);
    if (built == GeoBuildResult::Invalid) return;
    if (built == GeoBuildResult::MissingMember) {
        reply_err(op.sink(), "ERR could not decode requested zset member"); return;
    }
    if (built == GeoBuildResult::Oom) { reply_err(op.sink(), "ERR out of memory"); return; }
    const Slice destination_key = op.arg(options.destination_arg);
    const uint64_t destination_hash = FlatStore::hash_key(destination_key);
    if (output.empty()) {
        if (notify) notify_erase_image(shard, destination_hash, destination_key, true);
        else shard.store().erase_resident(destination_hash, destination_key);
        reply_int(op.sink(), 0);
        return;
    }
    KvObj* previous = shard.store().find_resident(destination_hash, destination_key);
    // Ignore elapsed residents without touching or reaping them before replacement admission.
    if (previous && shard.store().deadline(destination_hash, previous) >= 0 &&
        shard.store().watch_deadline(destination_hash, destination_key) < 0) previous = nullptr;
    // Redis setKey keeps the old destination's LRU/LFU bits, but STORE may compact the value.
    const uint8_t eviction_meta = previous ? previous->eviction_meta() : 0;
    const ZsetOwnerResult stored = zset_owner_replace(
        shard, destination_key, destination_hash, notify, output, -1, eviction_meta, false);
    if (stored != ZsetOwnerResult::Ok) { reply_owner_error(op, stored); return; }
    if (notify) {
        const NotifyEventId event = op.cmd_name().eq_icase("geosearchstore")
            ? NotifyEventId::Geosearchstore : NotifyEventId::Georadiusstore;
        notify_record(shard, op, NOTIFY_ZSET, event, destination_key);
    }
    reply_int(op.sink(), static_cast<long long>(output.size()));
}

CommandTable geo_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
