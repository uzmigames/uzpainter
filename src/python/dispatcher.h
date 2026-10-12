#pragma once

// The Python dispatcher thread (docs/architecture/02-runtime-topology.md §4,
// 10-python-api.md §4; task phase1.21_pyapi-dispatcher-lifecycle).
//
// One thread delivers `substance_painter.event` events and the facade's callbacks. A task is a
// Python callable queued by `Post` once the transition it reports is committed; the thread takes
// the GIL, calls it and drops it, in queue order. It never takes the document lock itself: a
// task that calls back into the API takes the lock inside that call like any other thread, so a
// handler observes the committed state and cannot deadlock against the thread that posted it.
// The thread is started on the first `Post` and lives as long as the process, so deliveries go on
// after the script that started an operation returned.
//
// - `WaitThrough(seq)`: another thread blocks (the GIL released by the caller) until every task
//   queued up to `seq` has run. A synchronous operation posts its event and waits, so the handlers
//   run on this thread yet before the operation returns, as Painter delivers them (Tier 0
//   `during_step`).
// - `RunInline(seq)`: on the dispatcher thread itself (a handler starting such an operation), the
//   queued tasks up to `seq` run right there, re-entrantly, instead of waiting for themselves.
// - `Hold` / `Release`: an asynchronous operation in flight that will post later (a mesh reload
//   on its worker thread). `Drain` waits until the queue is empty and nothing is held: the host
//   calls it after a script returned, before the process ends.

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <mutex>
#include <set>
#include <thread>
#include <utility>

#include <pybind11/pybind11.h>

namespace uzp::python {

class Dispatcher {
public:
    static Dispatcher& Get();

    /// Queues `task` (called with no argument on the dispatcher thread); returns its sequence
    /// number. Requires the GIL.
    std::uint64_t Post(pybind11::object task);
    /// The sequence number of the last task queued.
    std::uint64_t LastPosted() const;
    /// Blocks until every task up to `seq` has run. The caller must not hold the GIL and must not
    /// be the dispatcher thread.
    void WaitThrough(std::uint64_t seq);
    /// On the dispatcher thread, with the GIL: runs the queued tasks up to `seq` inline.
    void RunInline(std::uint64_t seq);
    /// Blocks until the queue is empty and nothing is held. The caller must not hold the GIL.
    void Drain();
    void Hold();
    void Release();

    bool OnDispatcherThread() const;
    /// `threading.get_ident()` of the dispatcher thread (0 before it started).
    unsigned long ThreadIdent() const;

private:
    Dispatcher() = default;
    void Work();
    /// Runs one task with the GIL held; a Python error is printed, never propagated.
    static void Run(pybind11::object& task);
    void Finished(std::uint64_t seq);

    mutable std::mutex mutex_;
    std::condition_variable queued_;
    std::condition_variable progressed_;
    std::deque<std::pair<std::uint64_t, pybind11::object>> queue_;
    /// Tasks queued or running.
    std::set<std::uint64_t> outstanding_;
    std::uint64_t next_ = 0;
    int holds_ = 0;
    bool started_ = false;
    std::thread::id thread_;
    unsigned long ident_ = 0;
};

}  // namespace uzp::python
