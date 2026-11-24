#include "../native/playback_handoff.h"

namespace {
using namespace std::chrono_literals;
using Microsoft::WRL::ComPtr;

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

struct DeviceLock {
    AVD3D11VADeviceContext* const device;
    explicit DeviceLock(const Producer& producer)
        : device(static_cast<AVD3D11VADeviceContext*>(reinterpret_cast<AVHWDeviceContext*>(
              producer.decoder->codec->hw_device_ctx->data)->hwctx)) {
        device->lock(device->lock_ctx);
    }
    ~DeviceLock() { device->unlock(device->lock_ctx); }
    DeviceLock(const DeviceLock&) = delete;
    DeviceLock& operator=(const DeviceLock&) = delete;
};

std::array<int64_t, 3> bufferedTicks(Producer& producer, Clip& clip) {
    std::unique_lock<std::mutex> lock(producer.guard);
    require(producer.changed.wait_for(lock, 5s, [&]{
        return (producer.queue.size() == 4 && !producer.decoding) || !producer.failure.empty();
    }), "source failed to buffer four decoded successors");
    require(producer.failure.empty() && producer.current && producer.current->format == AV_PIX_FMT_D3D11,
            "source did not produce a hardware frame");
    clip.timebase = producer.base;
    const auto first = producer.current->best_effort_timestamp - producer.origin;
    const auto second = producer.queue[0]->best_effort_timestamp - producer.origin;
    const auto third = producer.queue[1]->best_effort_timestamp - producer.origin;
    require(first + 1 < second && second < third, "fixture has no testable timestamp intervals");
    return {first, second, third};
}

void run(const char* fixture) {
    Clip primaryClip, peerClip;
    primaryClip.asset = "primary";
    peerClip.asset = "peer";
    primaryClip.path = peerClip.path = fixture;
    Producer primary(primaryClip, 0, nullptr, false, 8, 0, 0, -1, -1, true);
    Producer peer(peerClip, 0, nullptr, false, 8, 0, 0, -1, -1, true);
    auto [first, second, third] = bufferedTicks(primary, primaryClip);
    bufferedTicks(peer, peerClip);

    ComPtr<IDXGIAdapter> adapter;
    {
        DeviceLock lock(primary);
        ComPtr<IDXGIDevice> dxgi;
        check(lock.device->device->QueryInterface(IID_PPV_ARGS(&dxgi)), "producer DXGI device");
        check(dxgi->GetAdapter(&adapter), "producer adapter");
    }
    ComPtr<ID3D11Device> consumer;
    check(D3D11CreateDevice(adapter.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr, 0, nullptr, 0,
          D3D11_SDK_VERSION, &consumer, nullptr, nullptr), "consumer device");
    PlaybackHandoff handoff;
    constexpr int64_t playing = 1, seek = 2;

    auto service = [&](int64_t frame, int64_t tick, int64_t generation) {
        bool ready = false;
        auto selected = primary.at(primaryClip, frame, generation, tick, ready, false);
        require(ready && selected, "primary source interval is unproved");
        handoff.service(0, primaryClip, selected, primary, generation, consumer.Get());
        return handoff.pictures[0];
    };
    auto acquire = [&](int64_t frame, int64_t tick, int64_t generation) {
        const auto deadline = Clock::now() + 5s;
        do {
            if (auto picture = service(frame, tick, generation)) return picture;
            Sleep(1);
        } while (Clock::now() < deadline);
        throw std::runtime_error("exact primary source picture did not publish");
    };
    auto allowPrefetch = [&](int64_t frame, int64_t tick) {
        // Keep servicing the same real selection while the transfer worker
        // prepares its successor. Challenge prefetch with the lock held on
        // promotion, so a copy requested only at that point cannot pass.
        const auto deadline = Clock::now() + 500ms;
        do {
            require(bool(service(frame, tick, playing)), "held primary picture was lost");
            Sleep(1);
        } while (Clock::now() < deadline);
    };

    {
        DeviceLock stalledPeer(peer);
        // Request beyond the last available peer PTS while its producer is
        // blocked from delivering a successor. The selector can expose an
        // unverified floor for preparation, but no picture for composition.
        int64_t peerTick;
        {
            std::lock_guard<std::mutex> lock(peer.guard);
            peerTick = peer.queue.back()->best_effort_timestamp - peer.origin + 1;
        }
        auto serviceStalledPeer = [&](int64_t frame) {
            bool ready = false;
            auto selected = peer.at(peerClip, frame, playing, peerTick, ready, false);
            require(!ready && !selected, "peer unexpectedly proved its interval");
            require(!handoff.service(1, peerClip, selected, peer, playing, consumer.Get()),
                    "unproved peer picture reached composition");
        };
        const auto halfway = first + (second - first) / 2;
        {
            DeviceLock stalledCopy(primary);
            serviceStalledPeer(0);
            require(!service(0, first, playing), "blocked primary copy published");
            serviceStalledPeer(1);
            require(!service(1, halfway, playing), "blocked copy published after clock advanced");
        }
        auto a = acquire(1, halfway, playing);
        require(a.pts == first + primary.origin, "playback clock advancement lost the exact floor");
        allowPrefetch(1, halfway);

        PictureHandoff::Picture b;
        {
            DeviceLock blockNewCopy(primary);
            serviceStalledPeer(2);
            b = service(2, second, playing);
            require(b && b.pts == second + primary.origin && b.generation == a.generation && b.slot != a.slot,
                    "prefetched successor did not survive selection change with peer stalled");
        }
        allowPrefetch(2, second);

        {
            DeviceLock blockNewCopy(primary);
            serviceStalledPeer(3);
            auto c = service(3, third, playing);
            require(c && c.pts == third + primary.origin && c.slot == a.slot && c.generation == b.generation,
                    "stalled peer prevented producer slot retirement and reuse");
            // A seek can request the same exact PTS. Its previous transport's
            // lease must be unavailable until a new-generation copy completes.
            require(!service(3, third, seek), "true seek accepted a previous-generation picture");
        }
        auto refreshed = acquire(3, third, seek);
        require(refreshed.pts == third + primary.origin && refreshed.generation != b.generation,
                "post-seek acquisition did not use the new generation");
    }

    // Cancel a lane with a live consumer lease and the former stalled lane
    // with an outstanding or freshly prepared copy. Ring teardown owns drain.
    handoff.trim({});
    std::cout << "{\"scheduler\":\"passed\",\"clock_advanced_while_copy_blocked\":true,"
                 "\"successor_prepared_while_peer_unavailable\":true,\"slot_reused\":true,"
                 "\"seek_invalidated_picture\":true,\"teardown_completed\":true}\n";
}
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    av_log_set_level(AV_LOG_QUIET);
    try {
        run(argv[1]);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
