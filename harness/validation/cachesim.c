/*
 * cachesim.c — standalone trace-driven cache-replacement simulator.
 *
 * Offline analysis (no server, no network). Streams a Meta/CacheLib KV trace,
 * hashes each key to a uint64, and replays the access sequence under several
 * eviction/admission policies at a sweep of cache capacities.
 *
 * Policies:
 *   1. LRU     — evict least-recently-used.
 *   2. LFU     — evict resident key with lowest cumulative access count.
 *   3. BELADY  — oracle: evict resident key whose next access is farthest away.
 *   4. REUSE   — TinyLFU-style per-key recent-frequency predictor with
 *                admission control (admit only if incoming est >= victim est).
 *
 * Build: gcc -O3 -o /tmp/cachesim cachesim.c
 *
 * Trace columns (CSV): time,key,key_size,value_size,client_id,op,ttl
 * We use only col 2 (key); each line is one ACCESS.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define MAX_ACCESSES 1000000
#define LINE_BUF     4096

/* ------------------------------------------------------------------ */
/* FNV-1a hash of the key string                                      */
/* ------------------------------------------------------------------ */
static uint64_t fnv1a(const char *s, size_t n)
{
    uint64_t h = 1469598103934665603ULL;       /* FNV offset basis */
    for (size_t i = 0; i < n; i++) {
        h ^= (uint64_t)(unsigned char)s[i];
        h *= 1099511628211ULL;                 /* FNV prime */
    }
    return h;
}

/* ------------------------------------------------------------------ */
/* Open-addressing hash map: uint64 key -> int32 slot index.          */
/* Used both for distinct-key counting and as the per-policy index    */
/* mapping a key to its entry in the resident table.                  */
/* value == -1 means "empty". value == -2 means "tombstone".          */
/* ------------------------------------------------------------------ */
typedef struct {
    uint64_t *keys;
    int32_t  *vals;
    uint64_t  mask;     /* size - 1, size is power of two */
    size_t    count;    /* live entries */
    size_t    tombs;    /* tombstone slots */
} HMap;

static void hmap_init(HMap *m, size_t want)
{
    size_t cap = 16;
    while (cap < want * 2) cap <<= 1;          /* keep load factor <= 0.5 */
    m->keys = malloc(cap * sizeof(uint64_t));
    m->vals = malloc(cap * sizeof(int32_t));
    m->mask = cap - 1;
    m->count = 0;
    m->tombs = 0;
    for (size_t i = 0; i < cap; i++) m->vals[i] = -1;
}

static void hmap_free(HMap *m)
{
    free(m->keys);
    free(m->vals);
    m->keys = NULL;
    m->vals = NULL;
}

/* Rebuild the table in place, dropping all tombstones. Used when the
 * table fills with tombstones (open addressing with high delete churn).
 * Live (key,val) pairs are re-probed into a fresh slot array of the same
 * size, which is always sufficient because count <= size/2 by invariant. */
static void hmap_rehash(HMap *m)
{
    size_t cap = m->mask + 1;
    uint64_t *okeys = m->keys;
    int32_t  *ovals = m->vals;
    m->keys = malloc(cap * sizeof(uint64_t));
    m->vals = malloc(cap * sizeof(int32_t));
    for (size_t i = 0; i < cap; i++) m->vals[i] = -1;
    m->tombs = 0;
    size_t live = m->count;
    m->count = 0;
    for (size_t i = 0; i < cap; i++) {
        if (ovals[i] >= 0) {                    /* live entry */
            uint64_t key = okeys[i];
            size_t j = (size_t)(key & m->mask);
            while (m->vals[j] != -1) j = (j + 1) & m->mask;
            m->keys[j] = key;
            m->vals[j] = ovals[i];
            m->count++;
        }
    }
    (void)live;
    free(okeys);
    free(ovals);
}

/* Find slot for key. Returns index into the table arrays.
 * On hit, *found = 1. On miss, *found = 0 and the returned index is an
 * empty/tombstone slot where the caller may insert. */
static size_t hmap_slot(HMap *m, uint64_t key, int *found)
{
    size_t i = (size_t)(key & m->mask);
    size_t first_free = (size_t)-1;
    for (;;) {
        int32_t v = m->vals[i];
        if (v == -1) {                         /* empty: definitely absent */
            *found = 0;
            return (first_free != (size_t)-1) ? first_free : i;
        }
        if (v == -2) {                         /* tombstone: remember it */
            if (first_free == (size_t)-1) first_free = i;
        } else if (m->keys[i] == key) {
            *found = 1;
            return i;
        }
        i = (i + 1) & m->mask;
    }
}

/* Lookup: returns stored value or -1 if absent. */
static int32_t hmap_get(HMap *m, uint64_t key)
{
    int found;
    size_t i = hmap_slot(m, key, &found);
    return found ? m->vals[i] : -1;
}

/* Insert/overwrite key -> val. */
static void hmap_put(HMap *m, uint64_t key, int32_t val)
{
    /* If used slots (live + tombstones) approach the table size, compact.
     * This guarantees hmap_slot always finds an empty (-1) slot and never
     * loops forever. Threshold at 3/4 of the table. */
    size_t cap = m->mask + 1;
    if ((m->count + m->tombs) * 4 >= cap * 3)
        hmap_rehash(m);

    int found;
    size_t i = hmap_slot(m, key, &found);
    if (!found) {
        if (m->vals[i] == -2) m->tombs--;       /* reusing a tombstone slot */
        m->keys[i] = key;
        m->count++;
    }
    m->vals[i] = val;
}

/* Delete key (mark tombstone). */
static void hmap_del(HMap *m, uint64_t key)
{
    int found;
    size_t i = hmap_slot(m, key, &found);
    if (found) {
        m->vals[i] = -2;
        m->count--;
        m->tombs++;
    }
}

/* ------------------------------------------------------------------ */
/* Global access sequence                                             */
/* ------------------------------------------------------------------ */
static uint64_t *g_acc = NULL;     /* hashed key per access */
static int32_t  *g_next = NULL;    /* next access index touching same key, or N */
static size_t    g_n    = 0;       /* number of accesses */

/* ------------------------------------------------------------------ */
/* Min-heap over (next-use index) for BELADY, keyed by resident key.  */
/* We instead use a simpler approach: a binary max-heap on next-use,   */
/* so the root is the victim (farthest next use). Each heap node holds */
/* the key and its current next-use value. Because a key's next-use    */
/* changes as we advance, we use lazy invalidation: a heap entry is    */
/* valid only if it matches the key's currently-recorded next-use.     */
/*                                                                     */
/* To keep BELADY simple and provably correct without a complex heap,  */
/* we use a direct max-scan when capacity is small, but that is O(N*C). */
/* For correctness + speed we use a max-heap with lazy deletion below. */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/* Policy 1: LRU                                                      */
/* Doubly-linked list of resident keys + hash map key->node.          */
/* ------------------------------------------------------------------ */
typedef struct {
    uint64_t key;
    int32_t  prev;
    int32_t  next;
} LRUNode;

static double run_lru(size_t cap)
{
    LRUNode *nodes = malloc((cap + 1) * sizeof(LRUNode));
    HMap idx;                                  /* key -> node slot (0..cap-1) */
    hmap_init(&idx, cap);

    int32_t head = -1, tail = -1;              /* head = MRU, tail = LRU */
    int32_t *freelist = malloc((cap) * sizeof(int32_t));
    int32_t  freetop = 0;
    for (size_t i = 0; i < cap; i++) freelist[freetop++] = (int32_t)i;

    size_t hits = 0;

    for (size_t t = 0; t < g_n; t++) {
        uint64_t k = g_acc[t];
        int32_t slot = hmap_get(&idx, k);
        if (slot >= 0) {
            hits++;
            /* move node to head (MRU) */
            if (head != slot) {
                /* unlink */
                int32_t p = nodes[slot].prev, nx = nodes[slot].next;
                if (p >= 0) nodes[p].next = nx; else head = nx;
                if (nx >= 0) nodes[nx].prev = p; else tail = p;
                /* push front */
                nodes[slot].prev = -1;
                nodes[slot].next = head;
                if (head >= 0) nodes[head].prev = slot;
                head = slot;
                if (tail < 0) tail = slot;
            }
        } else {
            /* miss: insert; evict tail if full */
            if (idx.count >= cap) {
                int32_t victim = tail;
                hmap_del(&idx, nodes[victim].key);
                /* unlink tail */
                int32_t p = nodes[victim].prev;
                if (p >= 0) nodes[p].next = -1; else head = -1;
                tail = p;
                freelist[freetop++] = victim;
            }
            int32_t slotn = freelist[--freetop];
            nodes[slotn].key = k;
            nodes[slotn].prev = -1;
            nodes[slotn].next = head;
            if (head >= 0) nodes[head].prev = slotn;
            head = slotn;
            if (tail < 0) tail = slotn;
            hmap_put(&idx, k, slotn);
        }
    }

    hmap_free(&idx);
    free(nodes);
    free(freelist);
    return (double)hits / (double)g_n;
}

/* ------------------------------------------------------------------ */
/* Min-heap keyed on a 64-bit "metric"; root = minimum metric.        */
/* Holds resident-table slot indices; supports decrease/increase via  */
/* full re-heapify of a node. Used for LFU and REUSE eviction.        */
/* ------------------------------------------------------------------ */
typedef struct {
    int32_t  *slot;      /* heap[i] = resident slot index */
    int32_t   size;
} MinHeap;

/* Generic resident table shared by LFU/REUSE. */
typedef struct {
    uint64_t *key;       /* per resident slot: key */
    uint64_t *metric;    /* per resident slot: frequency metric (heap key) */
    int32_t  *heappos;   /* per resident slot: position in heap, or -1 */
} ResTab;

static ResTab  R;
static MinHeap H;

static void heap_swap(int32_t i, int32_t j)
{
    int32_t a = H.slot[i], b = H.slot[j];
    H.slot[i] = b; H.slot[j] = a;
    R.heappos[a] = j;
    R.heappos[b] = i;
}

static void heap_up(int32_t i)
{
    while (i > 0) {
        int32_t par = (i - 1) / 2;
        if (R.metric[H.slot[i]] < R.metric[H.slot[par]]) {
            heap_swap(i, par);
            i = par;
        } else break;
    }
}

static void heap_down(int32_t i)
{
    for (;;) {
        int32_t l = 2 * i + 1, r = 2 * i + 2, sm = i;
        if (l < H.size && R.metric[H.slot[l]] < R.metric[H.slot[sm]]) sm = l;
        if (r < H.size && R.metric[H.slot[r]] < R.metric[H.slot[sm]]) sm = r;
        if (sm == i) break;
        heap_swap(i, sm);
        i = sm;
    }
}

static void heap_push(int32_t resslot)
{
    int32_t i = H.size++;
    H.slot[i] = resslot;
    R.heappos[resslot] = i;
    heap_up(i);
}

static int32_t heap_min(void) { return H.slot[0]; }   /* lowest-metric slot */

/* Remove the root (min). The caller is responsible for clearing the
 * removed slot's heappos to -1. Moves the last element into the root and
 * sifts it down. */
static void heap_remove_root(void)
{
    H.size--;
    if (H.size > 0) {
        int32_t moved = H.slot[H.size];   /* old last element */
        H.slot[0] = moved;
        R.heappos[moved] = 0;
        heap_down(0);
    }
}

/* Update metric of a resident slot (already in heap) and re-heapify. */
static void heap_update(int32_t resslot)
{
    int32_t i = R.heappos[resslot];
    heap_up(i);
    heap_down(i);
}

/* ------------------------------------------------------------------ */
/* Policy 2: LFU — metric = cumulative access count.                  */
/* ------------------------------------------------------------------ */
static double run_lfu(size_t cap)
{
    R.key     = malloc(cap * sizeof(uint64_t));
    R.metric  = malloc(cap * sizeof(uint64_t));
    R.heappos = malloc(cap * sizeof(int32_t));
    H.slot    = malloc(cap * sizeof(int32_t));
    H.size    = 0;

    HMap idx;                                   /* key -> resident slot */
    hmap_init(&idx, cap);

    int32_t *freelist = malloc(cap * sizeof(int32_t));
    int32_t  freetop = 0;
    for (size_t i = 0; i < cap; i++) freelist[freetop++] = (int32_t)i;

    size_t hits = 0;

    for (size_t t = 0; t < g_n; t++) {
        uint64_t k = g_acc[t];
        int32_t slot = hmap_get(&idx, k);
        if (slot >= 0) {
            hits++;
            R.metric[slot] += 1;
            heap_update(slot);
        } else {
            if (idx.count >= cap) {
                int32_t victim = heap_min();
                hmap_del(&idx, R.key[victim]);
                heap_remove_root();
                R.heappos[victim] = -1;
                freelist[freetop++] = victim;
            }
            int32_t slotn = freelist[--freetop];
            R.key[slotn] = k;
            R.metric[slotn] = 1;
            heap_push(slotn);
            hmap_put(&idx, k, slotn);
        }
    }

    hmap_free(&idx);
    free(R.key); free(R.metric); free(R.heappos);
    free(H.slot); free(freelist);
    return (double)hits / (double)g_n;
}

/* ------------------------------------------------------------------ */
/* Policy 4: REUSE-PREDICTOR (TinyLFU-style)                          */
/* Per-key recent-frequency estimate, kept exact-per-key (not hashed) */
/* in a global map. Periodic halving (decay) every DECAY_WINDOW       */
/* accesses keeps it "recent". The resident-set eviction victim is the */
/* key with the lowest recent-frequency (min-heap). On a miss at      */
/* capacity, admission control: admit incoming only if its recent-freq */
/* estimate >= victim's; else keep the victim and skip the insert.    */
/* ------------------------------------------------------------------ */

/* Global per-key recent-frequency table (exact per key). */
typedef struct {
    uint64_t *keys;
    uint32_t *freq;
    uint64_t  mask;
    size_t    count;
} FreqMap;

static FreqMap F;

static void freqmap_init(FreqMap *fm, size_t want)
{
    size_t cap = 16;
    while (cap < want * 2) cap <<= 1;
    fm->keys = malloc(cap * sizeof(uint64_t));
    fm->freq = calloc(cap, sizeof(uint32_t));
    fm->mask = cap - 1;
    fm->count = 0;
    /* freq==0 marks empty; we never store a real 0 (we ++ on touch) */
}

static void freqmap_free(FreqMap *fm)
{
    free(fm->keys);
    free(fm->freq);
}

static uint32_t *freqmap_ref(FreqMap *fm, uint64_t key)
{
    size_t i = (size_t)(key & fm->mask);
    for (;;) {
        if (fm->freq[i] == 0) {                 /* empty slot */
            fm->keys[i] = key;
            fm->count++;
            return &fm->freq[i];
        }
        if (fm->keys[i] == key) return &fm->freq[i];
        i = (i + 1) & fm->mask;
    }
}

#define DECAY_WINDOW 100000u   /* halve all estimates every this many accesses */
#define FREQ_CAP     65535u    /* saturate to avoid overflow */

static void freqmap_decay(FreqMap *fm)
{
    size_t cap = fm->mask + 1;
    for (size_t i = 0; i < cap; i++) {
        if (fm->freq[i] != 0) {
            fm->freq[i] >>= 1;                  /* halve */
            /* note: an entry decaying to 0 becomes "empty" again, which is
             * fine — it simply means we've forgotten a long-cold key. */
            if (fm->freq[i] == 0) {
                /* leave key in place; slot now reusable. count stays an
                 * upper bound which is harmless for our purposes. */
            }
        }
    }
}

static double run_reuse(size_t cap, size_t distinct)
{
    R.key     = malloc(cap * sizeof(uint64_t));
    R.metric  = malloc(cap * sizeof(uint64_t));  /* recent-freq snapshot */
    R.heappos = malloc(cap * sizeof(int32_t));
    H.slot    = malloc(cap * sizeof(int32_t));
    H.size    = 0;

    HMap idx;
    hmap_init(&idx, cap);
    freqmap_init(&F, distinct);

    int32_t *freelist = malloc(cap * sizeof(int32_t));
    int32_t  freetop = 0;
    for (size_t i = 0; i < cap; i++) freelist[freetop++] = (int32_t)i;

    size_t hits = 0;
    size_t since_decay = 0;

    for (size_t t = 0; t < g_n; t++) {
        uint64_t k = g_acc[t];

        /* update recent-frequency estimate for this key (always) */
        uint32_t *fp = freqmap_ref(&F, k);
        if (*fp < FREQ_CAP) (*fp)++;
        uint32_t kfreq = *fp;

        if (++since_decay >= DECAY_WINDOW) {
            freqmap_decay(&F);
            since_decay = 0;
            /* refresh resident metric snapshots after global decay so the
             * heap stays consistent with decayed estimates */
            for (int32_t h = 0; h < H.size; h++) {
                int32_t rs = H.slot[h];
                uint32_t *rfp = freqmap_ref(&F, R.key[rs]);
                R.metric[rs] = *rfp;
            }
            /* rebuild heap order (cheap: cap is small) */
            for (int32_t i = H.size / 2 - 1; i >= 0; i--) heap_down(i);
        }

        int32_t slot = hmap_get(&idx, k);
        if (slot >= 0) {
            hits++;
            R.metric[slot] = kfreq;             /* refresh resident estimate */
            heap_update(slot);
        } else {
            if (idx.count >= cap) {
                /* admission control: compare incoming est vs victim est */
                int32_t victim = heap_min();
                uint64_t vfreq = R.metric[victim];
                if ((uint64_t)kfreq < vfreq) {
                    /* incoming is colder than the coldest resident: reject.
                     * (the resident set is unchanged; this is a true miss) */
                    continue;
                }
                /* admit: evict victim, insert incoming */
                hmap_del(&idx, R.key[victim]);
                heap_remove_root();
                R.heappos[victim] = -1;
                freelist[freetop++] = victim;
            }
            int32_t slotn = freelist[--freetop];
            R.key[slotn] = k;
            R.metric[slotn] = kfreq;
            heap_push(slotn);
            hmap_put(&idx, k, slotn);
        }
    }

    hmap_free(&idx);
    freqmap_free(&F);
    free(R.key); free(R.metric); free(R.heappos);
    free(H.slot); free(freelist);
    return (double)hits / (double)g_n;
}

/* ------------------------------------------------------------------ */
/* Policy 3: BELADY / OPT (oracle)                                    */
/* Evict the resident key whose NEXT use is farthest in the future    */
/* (or never = +inf). We use a max-heap on next-use over resident     */
/* keys with lazy invalidation: when a key is accessed, its old heap  */
/* entry's next-use no longer matches the freshly-computed one, so we  */
/* skip stale entries when popping a victim.                          */
/* g_next[t] = next index > t with same key, or g_n if none.          */
/* ------------------------------------------------------------------ */
typedef struct {
    int32_t  nextuse;    /* next-use index for the key at push time */
    uint64_t key;
} BHeapNode;

static BHeapNode *BH = NULL;
static int32_t    BHsize = 0;

static void bheap_swap(int32_t i, int32_t j)
{
    BHeapNode tmp = BH[i]; BH[i] = BH[j]; BH[j] = tmp;
}

static void bheap_up(int32_t i)
{
    while (i > 0) {
        int32_t par = (i - 1) / 2;
        if (BH[i].nextuse > BH[par].nextuse) { bheap_swap(i, par); i = par; }
        else break;
    }
}

static void bheap_down(int32_t i)
{
    for (;;) {
        int32_t l = 2 * i + 1, r = 2 * i + 2, big = i;
        if (l < BHsize && BH[l].nextuse > BH[big].nextuse) big = l;
        if (r < BHsize && BH[r].nextuse > BH[big].nextuse) big = r;
        if (big == i) break;
        bheap_swap(i, big);
        i = big;
    }
}

static void bheap_push(uint64_t key, int32_t nextuse)
{
    int32_t i = BHsize++;
    BH[i].key = key;
    BH[i].nextuse = nextuse;
    bheap_up(i);
}

static void bheap_pop(void)
{
    BH[0] = BH[--BHsize];
    if (BHsize > 0) bheap_down(0);
}

static double run_belady(size_t cap)
{
    /* idx: key -> current authoritative next-use index for resident key.
     * A heap entry is valid iff its nextuse == idx[key]. We allow the heap
     * to hold multiple entries per key (one per access); stale ones are
     * discarded lazily. Heap capacity bounded by total inserts, but we cap
     * it: we only push on insert and on access-refresh, so bound is g_n.   */
    BH = malloc((g_n + 1) * sizeof(BHeapNode));
    BHsize = 0;

    HMap idx;                                   /* key -> authoritative next-use */
    hmap_init(&idx, cap);

    /* resident membership: reuse a small map key->1 */
    HMap resident;
    hmap_init(&resident, cap);

    size_t hits = 0;

    for (size_t t = 0; t < g_n; t++) {
        uint64_t k = g_acc[t];
        int32_t nu = g_next[t];                 /* this key's next use after t */

        int32_t present = hmap_get(&resident, k);
        if (present == 1) {
            hits++;
            /* refresh authoritative next-use and push a fresh heap entry */
            hmap_put(&idx, k, nu);
            bheap_push(k, nu);
        } else {
            if (resident.count >= cap) {
                /* pop victim: skip stale heap entries */
                for (;;) {
                    uint64_t vk = BH[0].key;
                    int32_t  vnu = BH[0].nextuse;
                    int32_t  auth = hmap_get(&idx, vk);
                    if (auth == vnu && hmap_get(&resident, vk) == 1) {
                        /* valid victim */
                        bheap_pop();
                        hmap_del(&resident, vk);
                        hmap_del(&idx, vk);
                        break;
                    } else {
                        bheap_pop();            /* stale entry, drop it */
                    }
                }
            }
            hmap_put(&resident, k, 1);
            hmap_put(&idx, k, nu);
            bheap_push(k, nu);
        }
    }

    hmap_free(&idx);
    hmap_free(&resident);
    free(BH);
    BH = NULL;
    return (double)hits / (double)g_n;
}

/* ------------------------------------------------------------------ */
/* Load trace into g_acc, compute distinct count and g_next.          */
/* ------------------------------------------------------------------ */
static size_t count_distinct(void)
{
    HMap seen;
    hmap_init(&seen, g_n);                       /* worst case all distinct */
    for (size_t t = 0; t < g_n; t++) {
        if (hmap_get(&seen, g_acc[t]) < 0)
            hmap_put(&seen, g_acc[t], 1);
    }
    size_t d = seen.count;
    hmap_free(&seen);
    return d;
}

static void compute_next(void)
{
    /* g_next[t] = next index > t with same key, else g_n.
     * Backward pass with a "last seen position" map. */
    g_next = malloc(g_n * sizeof(int32_t));
    HMap last;                                   /* key -> last (later) index */
    hmap_init(&last, g_n);
    for (size_t i = g_n; i-- > 0; ) {
        int32_t prev = hmap_get(&last, g_acc[i]); /* index just after i with same key */
        g_next[i] = (prev >= 0) ? prev : (int32_t)g_n;
        hmap_put(&last, g_acc[i], (int32_t)i);
    }
    hmap_free(&last);
}

/* ------------------------------------------------------------------ */
/* main                                                               */
/* ------------------------------------------------------------------ */
int main(int argc, char **argv)
{
    const char *trace = "/home/henry/Projects/cache-trace/samples/2020Mar/cluster001";
    const char *outpath = "/tmp/cachesim_results.txt";
    if (argc > 1) trace = argv[1];

    FILE *f = fopen(trace, "r");
    if (!f) { fprintf(stderr, "cannot open trace %s\n", trace); return 1; }

    g_acc = malloc(MAX_ACCESSES * sizeof(uint64_t));
    if (!g_acc) { fprintf(stderr, "OOM\n"); return 1; }

    char line[LINE_BUF];
    fprintf(stderr, "[load] streaming trace %s ...\n", trace);
    while (g_n < MAX_ACCESSES && fgets(line, sizeof(line), f)) {
        /* column 2 = key. Find first comma, then key spans to second comma. */
        char *c1 = strchr(line, ',');
        if (!c1) continue;
        char *kstart = c1 + 1;
        char *c2 = strchr(kstart, ',');
        if (!c2) continue;
        size_t klen = (size_t)(c2 - kstart);
        g_acc[g_n++] = fnv1a(kstart, klen);
        if ((g_n % 200000) == 0)
            fprintf(stderr, "[load]   %zu accesses\n", g_n);
    }
    fclose(f);
    fprintf(stderr, "[load] done: %zu accesses\n", g_n);

    fprintf(stderr, "[prep] counting distinct keys ...\n");
    size_t distinct = count_distinct();
    fprintf(stderr, "[prep] distinct keys = %zu\n", distinct);

    fprintf(stderr, "[prep] computing next-use (BELADY) ...\n");
    compute_next();
    fprintf(stderr, "[prep] next-use done\n");

    const double fracs[] = {0.01, 0.02, 0.05, 0.10, 0.25, 0.50};
    const int    nfr = (int)(sizeof(fracs) / sizeof(fracs[0]));

    double lru_r[16], lfu_r[16], opt_r[16], reuse_r[16];
    size_t caps[16];

    for (int i = 0; i < nfr; i++) {
        size_t cap = (size_t)(fracs[i] * (double)distinct);
        if (cap < 1) cap = 1;
        caps[i] = cap;
        fprintf(stderr, "[run] size %.0f%% (cap=%zu keys)\n",
                fracs[i] * 100.0, cap);

        fprintf(stderr, "  LRU   ...\n"); lru_r[i]   = run_lru(cap);
        fprintf(stderr, "  LFU   ...\n"); lfu_r[i]   = run_lfu(cap);
        fprintf(stderr, "  BELADY...\n"); opt_r[i]   = run_belady(cap);
        fprintf(stderr, "  REUSE ...\n"); reuse_r[i] = run_reuse(cap, distinct);

        fprintf(stderr, "    LRU=%.2f%%  LFU=%.2f%%  OPT=%.2f%%  REUSE=%.2f%%\n",
                lru_r[i]*100, lfu_r[i]*100, opt_r[i]*100, reuse_r[i]*100);
    }

    /* ---- write results table ---- */
    FILE *o = fopen(outpath, "w");
    if (!o) { fprintf(stderr, "cannot open %s\n", outpath); return 1; }

    fprintf(o, "Trace: %s\n", trace);
    fprintf(o, "Accesses: %zu   Distinct keys: %zu\n", g_n, distinct);
    fprintf(o, "Reuse predictor: TinyLFU-style exact per-key recent-frequency,\n");
    fprintf(o, "  halving decay every %u accesses, admit iff est >= victim est.\n\n",
            DECAY_WINDOW);

    fprintf(o, "%-8s %-10s %12s %12s %12s %12s\n",
            "Size%", "Cap(keys)", "LRU", "LFU", "BELADY", "REUSE-PRED");
    fprintf(o, "%-8s %-10s %12s %12s %12s %12s\n",
            "-----", "---------", "------", "------", "------", "----------");
    for (int i = 0; i < nfr; i++) {
        fprintf(o, "%-8.0f %-10zu %11.2f%% %11.2f%% %11.2f%% %11.2f%%\n",
                fracs[i] * 100.0, caps[i],
                lru_r[i]*100, lfu_r[i]*100, opt_r[i]*100, reuse_r[i]*100);
    }

    /* ---- verdict ---- */
    fprintf(o, "\nVERDICT\n=======\n");
    for (int i = 0; i < nfr; i++) {
        double lru = lru_r[i]*100, lfu = lfu_r[i]*100;
        double opt = opt_r[i]*100, re = reuse_r[i]*100;
        double best_real = (lru > lfu) ? lru : lfu;
        double gap_to_opt = opt - re;
        double closed = 0.0;
        if (opt - best_real > 1e-9)
            closed = (re - best_real) / (opt - best_real) * 100.0;

        fprintf(o, "\nSize %.0f%% (cap=%zu):\n", fracs[i]*100.0, caps[i]);
        fprintf(o, "  REUSE %.2f%% vs LRU %.2f%% (%+.2f pp), vs LFU %.2f%% (%+.2f pp)\n",
                re, lru, re - lru, lfu, re - lfu);
        fprintf(o, "  Beats LRU: %s   Beats LFU: %s\n",
                (re > lru) ? "YES" : "no",
                (re > lfu) ? "YES" : "no");
        fprintf(o, "  BELADY ceiling %.2f%%; REUSE is %.2f pp below oracle",
                opt, gap_to_opt);
        if (opt - best_real > 1e-9)
            fprintf(o, "; closes %.1f%% of the best-real->oracle gap.\n", closed);
        else
            fprintf(o, ".\n");
    }

    /* aggregate verdict */
    int reuse_beats_lru = 0, reuse_beats_lfu = 0;
    double avg_gap = 0;
    for (int i = 0; i < nfr; i++) {
        if (reuse_r[i] > lru_r[i]) reuse_beats_lru++;
        if (reuse_r[i] > lfu_r[i]) reuse_beats_lfu++;
        avg_gap += (opt_r[i] - reuse_r[i]) * 100.0;
    }
    avg_gap /= nfr;
    fprintf(o, "\nSUMMARY\n-------\n");
    fprintf(o, "REUSE-PREDICTOR beats LRU at %d/%d sizes, beats LFU at %d/%d sizes.\n",
            reuse_beats_lru, nfr, reuse_beats_lfu, nfr);
    fprintf(o, "Average gap below BELADY oracle: %.2f pp.\n", avg_gap);

    fclose(o);
    fprintf(stderr, "[done] wrote %s\n", outpath);

    /* echo table to stdout too */
    printf("Wrote results to %s\n", outpath);
    free(g_acc);
    free(g_next);
    return 0;
}
