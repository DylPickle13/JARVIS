/* macOS-only directed ARP repair. No listener, credentials, routes or video.
 * Opens a non-promiscuous, ARP-only BPF handle, then permanently drops to nobody.
 * Keep Ethernet source local; only relay the freshly verified handset ARP query.
 */
#include "arp_protocol.h"
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <net/if_dl.h>
#include <pcap/pcap.h>
#include <pwd.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/file.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop_signal(int number) { (void)number; stopping = 1; }
static bool stopped(void *unused) { (void)unused; return stopping != 0; }
static double now(void *unused) {
    (void)unused; struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) _exit(70);
    return (double)t.tv_sec + (double)t.tv_nsec / 1e9;
}
static void wait_tick(void *unused) {
    (void)unused; struct timespec t = {0, 10000000}; nanosleep(&t, NULL);
}
static bool local_peer(const char *name, Peer *peer, struct in_addr *mask) {
    struct ifaddrs *all = NULL;
    if (getifaddrs(&all)) return false;
    int ips = 0, macs = 0;
    for (struct ifaddrs *p = all; p; p = p->ifa_next) {
        if (!p->ifa_addr || strcmp(name, p->ifa_name) || !(p->ifa_flags & IFF_UP) ||
            !(p->ifa_flags & IFF_RUNNING) || (p->ifa_flags & IFF_LOOPBACK)) continue;
        if (p->ifa_addr->sa_family == AF_INET && p->ifa_netmask) {
            peer->ip = ((struct sockaddr_in *)p->ifa_addr)->sin_addr;
            *mask = ((struct sockaddr_in *)p->ifa_netmask)->sin_addr; ips++;
        } else if (p->ifa_addr->sa_family == AF_LINK) {
            struct sockaddr_dl *d = (struct sockaddr_dl *)p->ifa_addr;
            if (d->sdl_alen == 6) { memcpy(peer->mac, LLADDR(d), 6); macs++; }
        }
    }
    freeifaddrs(all);
    return ips == 1 && macs == 1;
}
typedef struct { pcap_t *handle; bool failed; } Capture;
static int capture_read(void *context, const uint8_t **frame, size_t *length) {
    Capture *c = context;
    struct pcap_pkthdr *header;
    int r = pcap_next_ex(c->handle, &header, frame);
    if (r == 1) { *length = header->caplen; return 1; }
    if (r != 0) c->failed = true;
    return r == 0 ? 0 : -1;
}
static bool capture_send(void *context, const uint8_t *frame, size_t length) {
    Capture *c = context;
    if (stopping) return false;
    bool ok = pcap_inject(c->handle, frame, length) == (int)length;
    if (!ok) c->failed = true;
    return ok;
}
static pcap_t *open_capture(const char *interface, const Peer *local) {
    char error[PCAP_ERRBUF_SIZE], filter[256];
    pcap_t *p = pcap_create(interface, error);
    if (!p) return NULL;
    if (pcap_set_snaplen(p, 64) || pcap_set_promisc(p, 0) || pcap_set_timeout(p, 50) ||
        pcap_set_buffer_size(p, 65536) || pcap_set_immediate_mode(p, 1) || pcap_activate(p) != 0)
        goto fail;
    if (pcap_datalink(p) != DLT_EN10MB) goto fail;
    snprintf(filter, sizeof(filter),
             "arp and arp[6:2] = 2 and ether dst %02x:%02x:%02x:%02x:%02x:%02x",
             local->mac[0], local->mac[1], local->mac[2], local->mac[3], local->mac[4], local->mac[5]);
    struct bpf_program program;
    if (pcap_compile(p, &program, filter, 1, PCAP_NETMASK_UNKNOWN)) goto fail;
    int result = pcap_setfilter(p, &program); pcap_freecode(&program);
    if (result || pcap_setnonblock(p, 1, error)) goto fail;
    return p;
fail:
    pcap_close(p); return NULL;
}
static int singleton(void) {
    int fd = open("/var/run/com.jarvis.monitor-arp.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    struct stat info;
    if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_uid != 0 ||
        (info.st_mode & 0777) != 0600 || info.st_nlink != 1 || flock(fd, LOCK_EX | LOCK_NB)) {
        close(fd); return -1;
    }
    return fd;
}
static bool drop_privileges(void) {
    struct passwd *pw = getpwnam("nobody");
    if (!pw || pw->pw_uid == 0 || pw->pw_gid == 0) return false;
    uid_t uid = pw->pw_uid; gid_t gid = pw->pw_gid;
    if (setgroups(0, NULL) || setgid(gid) || setuid(uid)) return false;
    return getuid() == uid && geteuid() == uid && getgid() == gid && getegid() == gid && setuid(0) == -1;
}
int main(int argc, char **argv) {
    if (argc != 7 || (strcmp(argv[1], "--check") && strcmp(argv[1], "--once") && strcmp(argv[1], "--run"))) {
        fprintf(stderr, "usage: arp-repair-macos --check|--once|--run interface phone-ip phone-mac doorbell-ip doorbell-mac\n");
        return 64;
    }
    const char *interface = argv[2];
    if (!*interface || strlen(interface) >= IFNAMSIZ || strspn(interface, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-") != strlen(interface))
        return 64;
    Peer local, phone, doorbell; struct in_addr mask;
    if (!parse_peer(argv[3], argv[4], &phone) || !parse_peer(argv[5], argv[6], &doorbell)) return 64;
    if (!local_peer(interface, &local, &mask) || !valid_peers(&local, mask, &phone, &doorbell)) {
        fprintf(stderr, "status=invalid-interface-or-identities\n"); return 65;
    }
    if (!strcmp(argv[1], "--check")) {
        puts("status=configuration-valid network-test=not-performed"); return 0;
    }
    if (geteuid() != 0 || getuid() != 0) {
        fprintf(stderr, "status=administrator-install-required\n"); return 77;
    }
    unsigned bound_index = if_nametoindex(interface);
    if (!bound_index || privacy_redacted_mac(local.mac)) {
        fprintf(stderr, "status=privileged-interface-identity-unavailable\n"); return 69;
    }
    umask(077);
    struct rlimit limit = {0, 0};
    if (setrlimit(RLIMIT_CORE, &limit) || chdir("/")) return 70;
    int lock = singleton();
    if (lock < 0) { fprintf(stderr, "status=singleton-unavailable\n"); return 75; }
    pcap_t *capture = open_capture(interface, &local);
    if (!capture) { fprintf(stderr, "status=capture-unavailable\n"); close(lock); return 69; }
    /* Confirm the interface and its real MAC did not change while opening BPF. */
    Peer opened; struct in_addr opened_mask;
    if (!local_peer(interface, &opened, &opened_mask) ||
        if_nametoindex(interface) != bound_index || memcmp(opened.mac, local.mac, 6) ||
        !valid_peers(&opened, opened_mask, &phone, &doorbell)) {
        fprintf(stderr, "status=capture-binding-changed\n"); pcap_close(capture); close(lock); return 69;
    }
    if (!drop_privileges()) { pcap_close(capture); close(lock); return 77; }
    signal(SIGTERM, stop_signal); signal(SIGINT, stop_signal); signal(SIGPIPE, SIG_IGN);
    setvbuf(stdout, NULL, _IOLBF, 0);
    puts("status=ready privileges=nobody capture=arp-only-nonpromiscuous");
    Capture context = {capture, false};
    Transport io = {&context, capture_read, capture_send, now, wait_tick, stopped};
    const char *previous = ""; unsigned long long relayed = 0; double last_log = 0;
    bool once = !strcmp(argv[1], "--once"), redaction_reported = false;
    int result = 0;
    while (!stopping) {
        double began = now(NULL);
        Peer current; struct in_addr current_mask;
        const char *status;
        if (!local_peer(interface, &current, &current_mask)) status = "interface-unavailable";
        else {
            bool redacted = privacy_redacted_mac(current.mac);
            if (!bind_local_identity(&current, &local, if_nametoindex(interface), bound_index) ||
                !valid_peers(&current, current_mask, &phone, &doorbell)) status = "interface-unavailable";
            else {
                if (redacted && !redaction_reported) {
                    puts("status=local-mac-redacted binding=privileged-snapshot proof=fresh-directed-replies-required");
                    redaction_reported = true;
                }
                status = repair(&io, &current, &phone, &doorbell);
            }
        }
        if (context.failed) status = "capture-failed";
        if (!strcmp(status, "lookup-relayed")) relayed++;
        if (strcmp(status, previous) || began - last_log >= 60 || once) {
            printf("status=%s relayed=%llu\n", status, relayed); last_log = began; previous = status;
        }
        if (once) { result = strcmp(status, "lookup-relayed") ? 1 : 0; break; }
        /* A changed interface cannot be repaired with an old BPF binding. Let
         * launchd reopen it, rate-limited by ThrottleInterval, never re-escalate. */
        if (!strcmp(status, "interface-unavailable") || context.failed) { result = 69; break; }
        while (!stopping && now(NULL) < began + 10) wait_tick(NULL);
    }
    pcap_close(capture); close(lock); return result;
}
