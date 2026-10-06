/* Test-only adapter to the unmodified, external Redis 7.4 coordinate/formatting oracle. */
#include <stdarg.h>
#include <stddef.h>
#include "geohash.h"
#include "util.h"

int cdfix_oracle_geopos(double longitude, double latitude, double xy[2],
                       char *x, size_t xlen, char *y, size_t ylen) {
    GeoHashBits hash = {0};
    if (!geohashEncodeWGS84(longitude, latitude, GEO_STEP_MAX, &hash) ||
        !geohashDecodeToLongLatWGS84(hash, xy)) return 0;
    return ld2string(x, xlen, xy[0], LD_STR_HUMAN) > 0 &&
           ld2string(y, ylen, xy[1], LD_STR_HUMAN) > 0;
}
