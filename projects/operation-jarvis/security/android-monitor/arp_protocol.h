/* Shared, socket-independent ARP policy for the macOS monitor helper. */
#ifndef JARVIS_ARP_PROTOCOL_H
#define JARVIS_ARP_PROTOCOL_H
#include <arpa/inet.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct { uint8_t mac[6]; struct in_addr ip; } Peer;
static const uint8_t arp_header[6] = {0, 1, 8, 0, 6, 4};

static bool private_ip(struct in_addr ip) {
    uint32_t n = ntohl(ip.s_addr);
    return (n >> 24 == 10 || n >> 20 == 0xac1 || n >> 16 == 0xc0a8);
}
static bool valid_mac(const uint8_t *mac) {
    static const uint8_t zero[6] = {0};
    return !(mac[0] & 1) && memcmp(mac, zero, 6) != 0;
}
static bool privacy_redacted_mac(const uint8_t *mac) {
    static const uint8_t redacted[6] = {2, 0, 0, 0, 0, 0};
    return memcmp(mac, redacted, 6) == 0;
}
/* The capture is bound while privileged. A redacted enumeration is not a new
 * MAC identity: retain that binding, require its interface index, and still
 * demand BOTH fresh replies addressed to it before any handset query relay.
 * A real, different MAC (or a redacted privileged binding) is never accepted. */
static bool bind_local_identity(Peer *current, const Peer *bound,
                                unsigned current_index, unsigned bound_index) {
    if (!bound_index || current_index != bound_index || !valid_mac(bound->mac) ||
        privacy_redacted_mac(bound->mac)) return false;
    if (privacy_redacted_mac(current->mac)) memcpy(current->mac, bound->mac, 6);
    return memcmp(current->mac, bound->mac, 6) == 0;
}
static bool parse_peer(const char *ip, const char *mac, Peer *out) {
    if (inet_pton(AF_INET, ip, &out->ip) != 1 || !private_ip(out->ip) || strlen(mac) != 17)
        return false;
    for (int i = 0; i < 6; i++) {
        const char *hex = "0123456789abcdef";
        char a = mac[i * 3], b = mac[i * 3 + 1];
        if (a >= 'A' && a <= 'F') a += 'a' - 'A';
        if (b >= 'A' && b <= 'F') b += 'a' - 'A';
        const char *x = strchr(hex, a), *y = strchr(hex, b);
        if (!a || !b || !x || !y || (i < 5 && mac[i * 3 + 2] != ':')) return false;
        out->mac[i] = (uint8_t)((x - hex) * 16 + y - hex);
    }
    return valid_mac(out->mac) && !privacy_redacted_mac(out->mac);
}
static bool valid_peers(const Peer *local, struct in_addr mask, const Peer *phone, const Peer *doorbell) {
    const Peer *peers[] = {local, phone, doorbell};
    uint32_t m = ntohl(mask.s_addr), host = ~m;
    if (!m || (host & (host + 1)) || host < 3) return false;
    uint32_t net = ntohl(local->ip.s_addr) & m;
    for (int i = 0; i < 3; i++) {
        uint32_t ip = ntohl(peers[i]->ip.s_addr);
        if (!private_ip(peers[i]->ip) || !valid_mac(peers[i]->mac) ||
            (ip & m) != net || !(ip & host) || (ip & host) == host) return false;
        for (int j = 0; j < i; j++)
            if (peers[i]->ip.s_addr == peers[j]->ip.s_addr ||
                !memcmp(peers[i]->mac, peers[j]->mac, 6)) return false;
    }
    return true;
}
static void make_request(uint8_t frame[42], const Peer *local, const Peer *sender, const Peer *target) {
    memset(frame, 0, 42);
    memcpy(frame, target->mac, 6); memcpy(frame + 6, local->mac, 6);
    frame[12] = 8; frame[13] = 6; memcpy(frame + 14, arp_header, 6);
    frame[21] = 1;
    memcpy(frame + 22, sender->mac, 6); memcpy(frame + 28, &sender->ip, 4);
    memcpy(frame + 38, &target->ip, 4);
}
static bool is_reply(const uint8_t *f, size_t n, const Peer *source, const Peer *destination) {
    return n >= 42 && !memcmp(f, destination->mac, 6) && !memcmp(f + 6, source->mac, 6) &&
        f[12] == 8 && f[13] == 6 && !memcmp(f + 14, arp_header, 6) && f[20] == 0 && f[21] == 2 &&
        !memcmp(f + 22, source->mac, 6) && !memcmp(f + 28, &source->ip, 4) &&
        !memcmp(f + 32, destination->mac, 6) && !memcmp(f + 38, &destination->ip, 4);
}

/* read: 1 packet, 0 empty, -1 error. All reads nonblocking. No queued proof. */
typedef struct {
    void *context;
    int (*read)(void *, const uint8_t **, size_t *);
    bool (*send)(void *, const uint8_t *, size_t);
    double (*now)(void *);
    void (*wait)(void *);
    bool (*stopped)(void *);
} Transport;
static bool verified(Transport *io, const Peer *local, const Peer *peer) {
    const uint8_t *f; size_t n;
    int r = 0, i;
    for (i = 0; i < 128; i++) {
        r = io->read(io->context, &f, &n);
        if (r <= 0) break;
    }
    if (r < 0 || i == 128 || io->stopped(io->context)) return false;
    uint8_t request[42]; make_request(request, local, local, peer);
    if (!io->send(io->context, request, sizeof(request))) return false;
    double end = io->now(io->context) + 1.0;
    unsigned count = 0;
    while (!io->stopped(io->context) && io->now(io->context) < end && count < 4096) {
        r = io->read(io->context, &f, &n);
        if (r < 0) return false;
        if (r == 1) {
            count++;
            if (is_reply(f, n, peer, local)) return true;
        } else io->wait(io->context);
    }
    return false;
}
static const char *repair(Transport *io, const Peer *local, const Peer *phone, const Peer *doorbell) {
    if (!verified(io, local, doorbell)) return "doorbell-unverified";
    if (!verified(io, local, phone)) return "phone-unverified";
    if (io->stopped(io->context)) return "stopping";
    uint8_t f[42]; make_request(f, local, phone, doorbell);
    return io->send(io->context, f, sizeof(f)) ? "lookup-relayed" : "send-failed";
}
#endif
