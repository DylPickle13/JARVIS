#include "../arp_protocol.h"
#include <assert.h>

static Peer local, phone, camera;
static void reply(uint8_t *f, const Peer *source, const Peer *target) {
    make_request(f, source, source, target); f[21] = 2; memcpy(f + 32, target->mac, 6);
}
typedef struct {
    int sent, queued, response, stale, flood, error, send_failure;
    bool stop;
    double time;
    uint8_t frames[3][42], incoming[42];
} Fake;
static int read_fake(void *c, const uint8_t **f, size_t *n) {
    Fake *s = c;
    if (s->error) return -1;
    if (s->flood || s->stale > 0) {
        if (s->stale) s->stale--;
        reply(s->incoming, &camera, &local); *f = s->incoming; *n = 42; return 1;
    }
    if (!s->queued) return 0;
    s->queued = 0;
    reply(s->incoming, s->response == 3 ? &phone : (s->sent == 1 ? &camera : &phone), &local);
    *f = s->incoming; *n = 42; return 1;
}
static bool send_fake(void *c, const uint8_t *f, size_t n) {
    Fake *s = c; assert(n == 42); assert(s->sent < 3);
    memcpy(s->frames[s->sent++], f, n);
    if (s->send_failure) return false;
    s->queued = s->response && (s->response != 2 || s->sent == 1);
    return true;
}
static double now_fake(void *c) { return ((Fake *)c)->time; }
static void wait_fake(void *c) { ((Fake *)c)->time += .01; }
static bool stop_fake(void *c) { return ((Fake *)c)->stop; }
static Transport transport(Fake *f) {
    return (Transport){f, read_fake, send_fake, now_fake, wait_fake, stop_fake};
}
int main(void) {
    assert(parse_peer("192.168.40.10", "02:11:22:33:44:10", &local));
    assert(parse_peer("192.168.40.11", "02:11:22:33:44:11", &phone));
    assert(parse_peer("192.168.40.12", "02:11:22:33:44:12", &camera));
    struct in_addr mask; assert(inet_pton(AF_INET, "255.255.255.0", &mask) == 1);
    assert(valid_peers(&local, mask, &phone, &camera));
    Peer p;
    const char *bad_ips[] = {"8.8.8.8", "127.0.0.1", "169.254.2.1", "224.1.1.1", "::1", "192.168.1.999", "172.32.1.1"};
    for (size_t i = 0; i < sizeof(bad_ips) / sizeof(*bad_ips); i++)
        assert(!parse_peer(bad_ips[i], "02:11:22:33:44:10", &p));
    const char *bad_macs[] = {"ff:ff:ff:ff:ff:ff", "01:11:22:33:44:55", "00:00:00:00:00:00", "bad", "02-11:22:33:44:10", "02:11:22:33:44:gg", "02:11:22:33:44:1g", "02:11:22:33:44:10x"};
    for (size_t i = 0; i < sizeof(bad_macs) / sizeof(*bad_macs); i++)
        assert(!parse_peer("192.168.40.11", bad_macs[i], &p));
    assert(!parse_peer("192.168.40.11", "02:00:00:00:00:00", &p));
    Peer redacted = local; memset(redacted.mac, 0, 6); redacted.mac[0] = 2;
    p = redacted; assert(bind_local_identity(&p, &local, 7, 7));
    assert(!memcmp(p.mac, local.mac, 6));
    p = local; assert(bind_local_identity(&p, &local, 7, 7));
    p = redacted; assert(!bind_local_identity(&p, &local, 8, 7));
    p = redacted; assert(!bind_local_identity(&p, &local, 0, 0));
    p = redacted; assert(!bind_local_identity(&p, &redacted, 7, 7));
    p = phone; assert(!bind_local_identity(&p, &local, 7, 7));
    p = local; memset(p.mac, 0, 6); assert(!bind_local_identity(&p, &local, 7, 7));
    assert(parse_peer("172.16.1.2", "02:AA:BB:CC:DD:EF", &p));
    assert(parse_peer("10.1.2.3", "02:11:22:33:44:10", &p));
    assert(!valid_peers(&local, mask, &local, &camera));
    p = phone; memcpy(p.mac, local.mac, 6); assert(!valid_peers(&local, mask, &p, &camera));
    const char *bad_subnet[] = {"192.168.41.1", "192.168.40.0", "192.168.40.255"};
    for (int i = 0; i < 3; i++) {
        p = phone; inet_pton(AF_INET, bad_subnet[i], &p.ip);
        assert(!valid_peers(&local, mask, &p, &camera));
    }
    struct in_addr bad_mask; inet_pton(AF_INET, "255.0.255.0", &bad_mask);
    assert(!valid_peers(&local, bad_mask, &phone, &camera));
    uint8_t frame[60] = {0}; make_request(frame, &local, &phone, &camera);
    assert(!memcmp(frame, camera.mac, 6)); assert(!memcmp(frame + 6, local.mac, 6));
    assert(frame[21] == 1 && !memcmp(frame + 22, phone.mac, 6));
    assert(!memcmp(frame + 28, &phone.ip, 4) && !memcmp(frame + 38, &camera.ip, 4));
    reply(frame, &camera, &local);
    assert(is_reply(frame, 42, &camera, &local)); assert(is_reply(frame, 60, &camera, &local));
    assert(!is_reply(frame, 41, &camera, &local)); assert(!is_reply(frame, 0, &camera, &local));
    for (int i = 0; i < 42; i++) { frame[i] ^= 1; assert(!is_reply(frame, 42, &camera, &local)); frame[i] ^= 1; }
    Fake f = {.response = 1}; Transport io = transport(&f);
    assert(!strcmp(repair(&io, &local, &phone, &camera), "lookup-relayed")); assert(f.sent == 3);
    make_request(frame, &local, &phone, &camera); assert(!memcmp(frame, f.frames[2], 42));
    f = (Fake){0}; io = transport(&f);
    assert(!strcmp(repair(&io, &local, &phone, &camera), "doorbell-unverified")); assert(f.sent == 1);
    f = (Fake){.response = 2}; io = transport(&f);
    assert(!strcmp(repair(&io, &local, &phone, &camera), "phone-unverified")); assert(f.sent == 2);
    f = (Fake){.response = 3}; io = transport(&f);
    assert(!strcmp(repair(&io, &local, &phone, &camera), "doorbell-unverified")); assert(f.sent == 1);
    /* Redacted local enumeration does NOT waive fresh peer proof. */
    p = redacted; assert(bind_local_identity(&p, &local, 7, 7));
    f = (Fake){0}; io = transport(&f);
    assert(!strcmp(repair(&io, &p, &phone, &camera), "doorbell-unverified")); assert(f.sent == 1);
    f = (Fake){.response = 2}; io = transport(&f);
    assert(!strcmp(repair(&io, &p, &phone, &camera), "phone-unverified")); assert(f.sent == 2);
    f = (Fake){.response = 1}; io = transport(&f);
    assert(!strcmp(repair(&io, &p, &phone, &camera), "lookup-relayed")); assert(f.sent == 3);
    assert(!memcmp(f.frames[2] + 6, local.mac, 6));
    f = (Fake){.stale = 1}; io = transport(&f);
    assert(!verified(&io, &local, &camera)); assert(f.sent == 1);
    f = (Fake){.flood = 1}; io = transport(&f);
    assert(!verified(&io, &local, &camera)); assert(f.sent == 0);
    f = (Fake){.error = 1}; io = transport(&f);
    assert(!verified(&io, &local, &camera)); assert(f.sent == 0);
    f = (Fake){.send_failure = 1}; io = transport(&f);
    assert(!verified(&io, &local, &camera)); assert(f.sent == 1);
    f = (Fake){.stop = true}; io = transport(&f);
    assert(!verified(&io, &local, &camera)); assert(f.sent == 0);
    puts("ARP protocol tests passed (offline; no packet access).");
    return 0;
}
