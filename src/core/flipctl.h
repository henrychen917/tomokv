// flipctl.h -- allocation-free IO fingerprints and the single-owner FLIP controller.
//
// The writer is embedded in ThreadCtx, but only that physical thread mutates it while playing the
// IO role.  The monitor/controller reads completed cumulative windows; no per-operation atomic or
// shared-line write is introduced.  FlipController itself is written only by the main monitor
// thread.  INFO/DEBUG take its cold mutex and DEBUG's forced trigger is a single cold atomic flag.
#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace tomo {

class Server;

enum class FlipFingerprintClass : uint8_t {
    Read = 0,
    Write,
    MultiRead,
    MultiWrite,
    AtomicGrouped,
    Blocking,
    Other,
    Count,
};

inline constexpr size_t kFlipFingerprintClasses =
    static_cast<size_t>(FlipFingerprintClass::Count);

// Monotonic cumulative publication.  A controller subtraction therefore consumes every closed
// work window even when an IO thread closes many of them between monitor beats.
struct FlipFingerprintWindow {
    std::array<uint64_t, 4> pass_depth{};
    std::array<uint64_t, kFlipFingerprintClasses> command_class{};
    uint64_t commands = 0;
    uint64_t multikey_keys = 0;
    uint64_t multikey_ops = 0;
    uint64_t value_bytes = 0;
    uint64_t closed_windows = 0;
};

class FlipFingerprintWriter {
public:
    void configure(uint32_t commands_per_window) {
        work_window_ = commands_per_window;
        partial_ = {};
        published_ = {};
        pass_frames_ = 0;
    }

    bool enabled() const { return work_window_ != 0; }

    // Called only after the parsed frame has crossed its last refusal/backpressure point.
    void note_command(FlipFingerprintClass command_class, uint32_t keys,
                      uint64_t value_bytes) {
        partial_.command_class[static_cast<size_t>(command_class)]++;
        partial_.commands++;
        if (keys > 1) {
            partial_.multikey_keys += keys;
            partial_.multikey_ops++;
        }
        partial_.value_bytes += value_bytes;
        pass_frames_++;
    }

    // One bucket increment per parse pass, never one per frame.  The closing test lives here so a
    // deep pass pays one comparison and a work window may exceed N only by that already-completed
    // pass. Detection latency remains work based, independent of wall time.
    void finish_parse_pass() {
        const uint32_t frames = pass_frames_;
        pass_frames_ = 0;
        if (!frames) return;
        const size_t bucket = frames == 1 ? 0 : frames <= 4 ? 1 : frames <= 16 ? 2 : 3;
        partial_.pass_depth[bucket]++;
        if (partial_.commands < work_window_) return;
        for (size_t i = 0; i < published_.pass_depth.size(); i++)
            published_.pass_depth[i] += partial_.pass_depth[i];
        for (size_t i = 0; i < published_.command_class.size(); i++)
            published_.command_class[i] += partial_.command_class[i];
        published_.commands += partial_.commands;
        published_.multikey_keys += partial_.multikey_keys;
        published_.multikey_ops += partial_.multikey_ops;
        published_.value_bytes += partial_.value_bytes;
        // Keep this as the last owner store. The exceptional monitor reader checks this field
        // before consuming the cumulative counters, matching the tree's other owner-local INFO
        // counters without adding an atomic publication to the request path.
        published_.closed_windows++;
        partial_ = {};
    }

    const FlipFingerprintWindow& published() const { return published_; }

private:
    uint32_t work_window_ = 0;
    uint32_t pass_frames_ = 0;
    FlipFingerprintWindow partial_{};
    FlipFingerprintWindow published_{};
};

struct FlipSignature {
    std::array<double, 4> pass_depth{};
    std::array<double, kFlipFingerprintClasses> command_class{};
    double keys_per_multikey = 0;
    double value_bytes_per_command = 0;
    uint64_t commands = 0;
    bool valid = false;
};

FlipSignature flip_signature(const FlipFingerprintWindow& sample);
// The workload-mix distance. It deliberately EXCLUDES pass_depth: parse-pass occupancy is an
// arrival-batching observation the controller's own actuator moves (a measured io 5->7 step moved
// it by 0.048 while the mix families moved by 4e-7), and the sweep-abandon law says a signal the
// actuator moves cannot police the actuator. pass_depth stays measured, published and dumped for
// diagnosis; it is simply not trigger evidence.
double flip_signature_distance(const FlipSignature& left, const FlipSignature& right);
// Whole-signature distance including pass_depth. Diagnostics only -- never a trigger input.
double flip_signature_pass_distance(const FlipSignature& left, const FlipSignature& right);

// Small, deterministic detector used by both the controller and the unit test. In auto mode its
// band is twice the signature's own adjacent-window EWMA jitter, with one observed-command quantum
// as the floor. A numeric band is a percent; zero disables shift triggering.
class FlipShiftDetector {
public:
    explicit FlipShiftDetector(int32_t configured_band = -1)
        : configured_band_(configured_band) {}

    void reset();
    bool observe(const FlipFingerprintWindow& sample);
    void anchor();

    bool anchored() const { return anchored_; }
    // Cold diagnostic readers (DEBUG FLIPCTL only): the two vectors whose distance is the
    // fingerprint trigger, so an operator can see WHICH feature family moved.
    const FlipSignature& smoothed() const { return smoothed_; }
    const FlipSignature& anchored_signature() const { return anchored_signature_; }
    double band() const { return band_; }
    double last_distance() const { return last_distance_; }
    double jitter() const { return jitter_; }

private:
    void update_band();

    int32_t configured_band_ = -1;
    FlipSignature smoothed_{};
    FlipSignature previous_{};
    FlipSignature learning_origin_{};
    FlipSignature anchored_signature_{};
    double jitter_ = 0;
    double band_ = 0;
    double last_distance_ = 0;
    bool have_previous_ = false;
    bool have_jitter_ = false;
    bool anchored_ = false;
};

enum class FlipctlTriggerReason : uint8_t {
    None = 0,
    Boot,
    FingerprintShift,
    AnchorRateSurge,
    AnchorRateCollapse,
    Forced,
};

struct FlipctlReport {
    std::string state = "disabled";
    std::string phase = "disabled";
    std::string last_trigger = "none";
    uint32_t anchor_io = 0;
    uint32_t anchor_ex = 0;
    double anchor_rate = 0;
    double signature_band = 0;
    double rate_band = 0;
    uint64_t triggers = 0;
    uint64_t boot_triggers = 0;
    uint64_t fingerprint_triggers = 0;
    uint64_t rate_surge_triggers = 0;
    uint64_t rate_collapse_triggers = 0;
    uint64_t forced_triggers = 0;
    uint64_t null_maneuvers = 0;
    uint64_t model_holds = 0;
    uint32_t shift_confirmations = 0;
    uint32_t rate_confirmations = 0;
};

class FlipController {
public:
    FlipController() = default;
    FlipController(const FlipController&) = delete;
    FlipController& operator=(const FlipController&) = delete;

    bool init(bool enabled, int32_t configured_band, uint32_t nthreads);
    bool enabled() const { return enabled_; }
    uint32_t signal_sample_rate() const {
        return signal_sample_rate_.load(std::memory_order_relaxed);
    }
    void request_forced_trigger() {
        force_requested_.store(true, std::memory_order_release);
    }

    // Called only by the main monitor thread. Returns true when a new internal FLIP was issued.
    bool tick(Server& server, uint64_t now_ms);
    FlipctlReport report() const;
    std::string debug_dump() const;

private:
    enum class Phase : uint8_t {
        Disabled = 0,
        BootPending,
        Measuring,
        WaitingFlip,
        Seeking,
        Settling,
        Anchored,
    };

    struct ThreadMeasure {
        uint64_t ops = 0;
        uint64_t busy_ns = 0;
        uint64_t iterations = 0;
        uint64_t spins = 0;
    };

    struct Reading {
        uint32_t split = 0;
        double rate = 0;
    };

    struct MovementStamp {
        uint64_t flip_completed = 0;
        uint64_t flip_refused = 0;
        uint64_t flip_rebinds = 0;
        uint64_t bucket_moves = 0;
        uint64_t client_moves = 0;

        bool operator==(const MovementStamp&) const = default;
    };

    static const char* phase_name(Phase phase);
    static const char* reason_name(FlipctlTriggerReason reason);
    void start_maneuver(Server& server, FlipctlTriggerReason reason, uint64_t now_ms);
    bool sample_fingerprint(Server& server);
    bool sample_rate(Server& server, uint64_t now_ms, double& rate);
    bool sample_stabilized_rate(Server& server, uint64_t now_ms, double& rate);
    bool sample_anchored_rate(Server& server, uint64_t now_ms, double& rate);
    bool boot_load_stable(Server& server, uint64_t now_ms);
    MovementStamp movement_stamp(const Server& server) const;
    uint64_t total_commands(const Server& server) const;
    void enter_settling();
    bool sample_role_demand(Server& server, double& io_frac);
    bool issue_initial_jump(Server& server, uint32_t coordinator, double rate);
    bool issue_flip(Server& server, uint32_t coordinator, uint32_t target_io,
                    Phase after_flip);
    bool seek_after_reading(Server& server, uint32_t coordinator, double rate);
    bool settle(Server& server, uint32_t coordinator);
    void anchor(Server& server, double rate);
    void record(uint32_t split, double rate);
    bool visited(uint32_t split) const;
    double automatic_rate_band(double pair_delta, double rate) const;

    mutable std::mutex mutex_;
    bool enabled_ = false;
    int32_t configured_band_ = -1;
    Phase phase_ = Phase::Disabled;
    Phase after_flip_ = Phase::Seeking;
    FlipctlTriggerReason last_trigger_ = FlipctlTriggerReason::None;
    std::atomic<bool> force_requested_{false};
    std::atomic<uint32_t> signal_sample_rate_{0};

    std::vector<FlipFingerprintWindow> fingerprint_last_;
    FlipShiftDetector shift_detector_{};
    std::vector<ThreadMeasure> maneuver_start_;
    std::vector<ThreadMeasure> maneuver_mark_;
    std::vector<Reading> readings_;

    uint64_t triggers_ = 0;
    uint64_t boot_triggers_ = 0;
    uint64_t fingerprint_triggers_ = 0;
    uint64_t rate_surge_triggers_ = 0;
    uint64_t rate_collapse_triggers_ = 0;
    uint64_t forced_triggers_ = 0;

    uint32_t anchor_io_ = 0;
    uint32_t anchor_ex_ = 0;
    double anchor_rate_ = 0;
    double anchor_rate_jitter_ = 0;
    double anchor_rate_band_ = 0;
    double anchor_rate_band_floor_ = 0;
    uint32_t surge_streak_ = 0;
    uint32_t collapse_streak_ = 0;

    uint32_t maneuver_origin_io_ = 0;
    // The placement model's own observation window. Three demand estimates give a mean and the
    // spread that says how much of that mean is estimator noise.
    static constexpr uint32_t kModelWindow = 3;
    std::array<double, kModelWindow> model_io_frac_history_{};
    uint32_t model_io_frac_samples_ = 0;
    double model_io_frac_ = 0;
    double model_io_frac_noise_ = 0;
    uint64_t model_holds_ = 0;
    uint32_t model_equal_io_ = 0;
    uint64_t null_maneuvers_ = 0;
    // OUTCOME BACKOFF. Every trigger already demands consecutive confirming control passes before
    // it starts a maneuver. When a maneuver ends on the split it started from it delivered nothing,
    // so the next excursion of that kind must present MORE passes of evidence, not clear a wider
    // threshold: widening a threshold on a distance normalized to [0,1] can put it out of reach of
    // any workload change at all and silently retire the detector, while a longer window keeps full
    // sensitivity and only costs time. Doubling per null result, halving back to the floor when a
    // maneuver actually moves the split, bounded by the window the controller already needs to
    // learn an anchor -- past that it would take longer to NOTICE a change than to characterize
    // one. Not a knob: both ends are derived.
    static constexpr uint32_t kMinConfirmations = 2;
    uint32_t shift_confirmations_ = kMinConfirmations;
    uint32_t rate_confirmations_ = kMinConfirmations;
    uint32_t shift_streak_ = 0;
    uint32_t pending_target_io_ = 0;
    uint64_t pending_completed_ = 0;
    uint64_t pending_refused_ = 0;
    int direction_ = 0;
    uint32_t step_units_ = 0;
    uint32_t step_one_reversals_ = 0;
    double previous_rate_ = 0;

    uint64_t rate_window_ms_ = 0;
    uint64_t rate_window_commands_ = 0;
    MovementStamp rate_window_movement_{};
    double previous_subwindow_rate_ = 0;
    double stable_pair_delta_ = 0;
    double boot_rate_ewma_ = 0;
    double boot_rate_jitter_ = 0;
    double boot_rate_slope_ = 0;
    double boot_rate_slope_threshold_ = 0;
    double boot_previous_ewma_change_ = 0;
    double anchor_learning_rate_jitter_ = 0;
    double anchor_learning_rate_sum_ = 0;
    double anchor_learning_rate_min_ = 0;
    double anchor_learning_rate_max_ = 0;
    uint32_t anchor_learning_rate_samples_ = 0;
    bool previous_subwindow_valid_ = false;
    bool boot_rate_ewma_valid_ = false;
    bool boot_previous_ewma_change_valid_ = false;
    bool boot_rate_jitter_valid_ = false;
    bool boot_work_observed_ = false;
    static constexpr uint32_t kBootTrendTicks = 5;
    std::array<double, kBootTrendTicks> boot_rate_history_{};
    uint32_t boot_rate_samples_ = 0;
    uint32_t boot_nonidle_ticks_ = 0;

    uint32_t anchor_signature_samples_ = 0;
    uint32_t signature_learning_windows_ = 1;
    uint32_t maneuver_learning_windows_ = 1;
    bool fingerprint_sampled_this_tick_ = false;
    bool anchor_sampling_disabled_ = false;
    uint32_t maneuver_signature_samples_ = 0;
    bool retrigger_after_flip_ = false;
    FlipctlTriggerReason pending_retrigger_ = FlipctlTriggerReason::None;
    double last_shift_distance_ = 0;
    double last_shift_band_ = 0;
};

}  // namespace tomo
