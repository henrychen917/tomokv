// Included inside CoreConcurrencyTest. Real controller transitions, no listener or worker loop.
// The route row owns these checks; selectors permit one-site throwaway mutation controls.
static void flipsettle_check(const char* site, const char* field, bool ok) {
    if (!ok) {
        std::fprintf(stderr, "FAIL flipsettle %s: %s\n", site, field);
        std::_Exit(1);
    }
}

static bool flipsettle_signature_equal(const FlipSignature& a, const FlipSignature& b) {
    return a.pass_depth == b.pass_depth && a.command_class == b.command_class &&
           a.keys_per_multikey == b.keys_per_multikey &&
           a.value_bytes_per_command == b.value_bytes_per_command &&
           a.commands == b.commands && a.valid == b.valid;
}

static bool flipsettle_detector_equal(FlipShiftDetector a, FlipShiftDetector b) {
    // Also probe the hidden previous/origin/noise state through its production consumers.
    for (unsigned step = 0; step != 5; ++step) {
        if (a.anchored() != b.anchored() || a.band() != b.band() ||
            a.last_distance() != b.last_distance() || a.jitter() != b.jitter() ||
            a.noise_bound() != b.noise_bound() || a.noise_samples() != b.noise_samples() ||
            !flipsettle_signature_equal(a.smoothed(), b.smoothed()) ||
            !flipsettle_signature_equal(a.anchored_signature(), b.anchored_signature()))
            return false;
        FlipFingerprintWindow w;
        w.commands = 1000 + step * 100;
        w.closed_windows = 1;
        w.pass_depth[step % 4] = 10 + step;
        w.command_class[0] = 900 - step * 100;
        w.command_class[1] = w.commands - w.command_class[0];
        w.multikey_ops = 17 + step;
        w.multikey_keys = 71 + step;
        w.value_bytes = 65536 + step * 1024;
        if (a.observe(w) != b.observe(w)) return false;
        if (step == 2) { a.anchor(); b.anchor(); }
    }
    return true;
}

static void flipsettle(const char* site, uint32_t databases = 1) {
    using Phase = FlipController::Phase;
    const bool enter = std::strcmp(site, "seek") == 0;
    const bool waiting = std::strcmp(site, "waiting") == 0;
    const bool other = std::strcmp(site, "nonsettling") == 0;
    const bool disarm = std::strcmp(site, "disarm") == 0;
    require(enter || waiting || other || disarm, "known flipsettle transition selector");
    Fixture<false> f(false, 8, 16, databases); // existing 6 IO + 2 EX fixture, no boot
    auto& c = f.server.flipctl_;
    require(c.init(true, 8), "initialize flipsettle controller");
    c.phase_ = enter ? Phase::Seeking : disarm ? Phase::Settling : Phase::WaitingFlip;
    c.after_flip_ = other ? Phase::Seeking : Phase::Settling;
    c.seek_ = FlipController::Seek::Returning;
    c.pending_completed_ = 46;
    c.pending_target_io_ = 6;
    f.server.flip_completed_.store(47, std::memory_order_relaxed);
    c.anchor_signature_samples_ = 11;
    c.maneuver_signature_samples_ = 13;
    c.anchor_learning_rate_jitter_ = 0.125;
    c.anchor_learning_rate_sum_ = 17001;
    c.anchor_learning_rate_min_ = 17002;
    c.anchor_learning_rate_max_ = 17003;
    c.anchor_learning_rate_samples_ = 19;
    FlipFingerprintWindow w;
    w.commands = 1000;
    w.closed_windows = 1;
    w.command_class[0] = 800;
    w.command_class[1] = 200;
    w.pass_depth[0] = 1000;
    w.value_bytes = 64000;
    c.shift_detector_.observe(w);
    w.command_class[0] = 790;
    w.command_class[1] = 210;
    c.shift_detector_.observe(w);
    c.shift_detector_.anchor();
    w.command_class[0] = 200;
    w.command_class[1] = 800;
    c.shift_detector_.observe(w);
    // An unentered learning window is a failure, including in the fixture itself.
    flipsettle_check(site, "detector-seed", c.shift_detector_.anchored() && c.shift_detector_.jitter() > 0 &&
            c.shift_detector_.noise_samples() > 0 && c.shift_detector_.last_distance() > 0);
    c.signal_sample_rate_.store(23, std::memory_order_release);
    c.anchor_sampling_disabled_ = false;
    c.rate_window_ms_ = 29;
    c.previous_subwindow_valid_ = true;
    // Nonzero sentinels on surrounding state. The byte mask below covers ALL other controller
    // members, including vectors, counters, trigger state, windows, confirmations and the mutex.
    c.rate_window_commands_ = 31;
    c.rate_sample_commands_ = 37;
    c.previous_subwindow_commands_ = 41;
    c.previous_subwindow_rate_ = 43;
    c.rate_window_movement_ = {47, 53, 59, 61, 67};
    c.anchor_rate_ = 71;
    c.anchor_rate_jitter_ = 0.25;
    c.anchor_rate_band_ = 0.375;
    c.anchor_rate_band_floor_ = 0.5;
    c.maneuver_rate_jitter_ = 0.625;
    c.stable_pair_delta_ = 0.125;
    c.shift_streak_ = 73;
    c.surge_streak_ = 79;
    c.collapse_streak_ = 83;
    c.stationary_since_ms_ = 89;
    c.readings_.push_back({6, 1024});
    FlipShiftDetector expected_detector = c.shift_detector_;
    if (!other) expected_detector.reset();

    std::array<unsigned char, sizeof(FlipController)> before;
    std::memcpy(before.data(), &c, sizeof c);
    std::array<bool, sizeof(FlipController)> allowed{};
    const auto allow = [&](const auto& member) {
        const size_t at = reinterpret_cast<const unsigned char*>(&member) -
                          reinterpret_cast<const unsigned char*>(&c);
        std::fill_n(allowed.begin() + at, sizeof member, true);
    };
    allow(c.phase_);
    if (!other) {
        allow(c.shift_detector_);
        allow(c.anchor_signature_samples_);
        allow(c.maneuver_signature_samples_);
        allow(c.anchor_learning_rate_jitter_);
        allow(c.anchor_learning_rate_sum_);
        allow(c.anchor_learning_rate_min_);
        allow(c.anchor_learning_rate_max_);
        allow(c.anchor_learning_rate_samples_);
    }
    allow(c.rate_window_ms_);
    allow(c.previous_subwindow_valid_);
    if (disarm) { allow(c.signal_sample_rate_); allow(c.anchor_sampling_disabled_); }
    if (enter) { allow(c.readings_); allow(c.seek_); }

    // Seek->settle follows the real reading/argmax path. The other sites use the entire tick,
    // including fingerprint collection, completion detection and the original mutex scope.
    const bool issued = enter ? c.seek_after_reading(f.server, 0, 1000, 16384)
                              : c.tick(f.server, 1000);
    flipsettle_check(site, "phase", !issued && c.phase_ == (other ? Phase::Seeking : Phase::Settling));
    flipsettle_check(site, "shift_detector_", flipsettle_detector_equal(c.shift_detector_, expected_detector));
    flipsettle_check(site, "anchor_signature_samples_", c.anchor_signature_samples_ == (other ? 11u : 0u));
    flipsettle_check(site, "maneuver_signature_samples_", c.maneuver_signature_samples_ == (other ? 13u : 0u));
    flipsettle_check(site, "anchor_learning_rate_jitter_", c.anchor_learning_rate_jitter_ == (other ? 0.125 : 0));
    flipsettle_check(site, "anchor_learning_rate_sum_", c.anchor_learning_rate_sum_ == (other ? 17001 : 0));
    flipsettle_check(site, "anchor_learning_rate_min_", c.anchor_learning_rate_min_ == (other ? 17002 : 0));
    flipsettle_check(site, "anchor_learning_rate_max_", c.anchor_learning_rate_max_ == (other ? 17003 : 0));
    flipsettle_check(site, "anchor_learning_rate_samples_", c.anchor_learning_rate_samples_ == (other ? 19u : 0u));
    flipsettle_check(site, "rate_window_ms_", c.rate_window_ms_ == 0);
    flipsettle_check(site, "previous_subwindow_valid_", !c.previous_subwindow_valid_);
    flipsettle_check(site, "sampling-disarmed", c.signal_sample_rate() == (disarm ? 0u : 23u));
    flipsettle_check(site, "anchor_sampling_disabled_", c.anchor_sampling_disabled_ == disarm);
    if (enter) {
        flipsettle_check(site, "seek-record", c.seek_ == FlipController::Seek::None &&
            c.readings_.size() == 2 && c.readings_[0].split == 6 && c.readings_[0].rate == 1024 &&
            c.readings_[1].split == 6 && c.readings_[1].rate == 16384);
    }
    const auto* after = reinterpret_cast<const unsigned char*>(&c);
    bool preserved = true;
    for (size_t i = 0; i != before.size(); ++i)
        preserved &= allowed[i] || before[i] == after[i];
    flipsettle_check(site, "unrelated-state", preserved);
    std::printf("TRACE flipsettle %s databases=%u phase=%s samples=%u/%u learning=%.3f/%.0f/%.0f/%.0f/%u "
                "signal=%u disabled=%u window=%llu paired=%u preserved=1\n",
                site, databases, c.phase_name(c.phase_), c.anchor_signature_samples_, c.maneuver_signature_samples_,
                c.anchor_learning_rate_jitter_, c.anchor_learning_rate_sum_, c.anchor_learning_rate_min_,
                c.anchor_learning_rate_max_, c.anchor_learning_rate_samples_, c.signal_sample_rate(),
                c.anchor_sampling_disabled_, static_cast<unsigned long long>(c.rate_window_ms_),
                c.previous_subwindow_valid_);
}

static void flipsettle_all() {
    for (uint32_t databases : {1u, 4u}) {
        if (kSingleDatabase && databases != 1) continue;
        for (const char* site : {"seek", "waiting", "nonsettling", "disarm"}) flipsettle(site, databases);
    }
}
