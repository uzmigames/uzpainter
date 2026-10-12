// The Python dispatcher thread (dispatcher.h).

#include "python/dispatcher.h"

#include <exception>

namespace py = pybind11;

namespace uzp::python {

Dispatcher& Dispatcher::Get() {
    static Dispatcher* dispatcher = new Dispatcher();  // its thread outlives every static destructor
    return *dispatcher;
}

std::uint64_t Dispatcher::Post(py::object task) {
    std::lock_guard lock(mutex_);
    const std::uint64_t seq = ++next_;
    queue_.emplace_back(seq, std::move(task));  // a move: no reference count changes without the GIL
    outstanding_.insert(seq);
    if (!started_) {
        started_ = true;
        std::thread([this] { Work(); }).detach();
    }
    queued_.notify_one();
    return seq;
}

std::uint64_t Dispatcher::LastPosted() const {
    std::lock_guard lock(mutex_);
    return next_;
}

void Dispatcher::WaitThrough(std::uint64_t seq) {
    std::unique_lock lock(mutex_);
    progressed_.wait(lock, [&] { return outstanding_.empty() || *outstanding_.begin() > seq; });
}

void Dispatcher::RunInline(std::uint64_t seq) {
    for (;;) {
        std::pair<std::uint64_t, py::object> task;
        {
            std::lock_guard lock(mutex_);
            if (queue_.empty() || queue_.front().first > seq) return;
            task = std::move(queue_.front());
            queue_.pop_front();
        }
        Run(task.second);
        task.second = py::object();  // released with the GIL held
        Finished(task.first);
    }
}

void Dispatcher::Drain() {
    std::unique_lock lock(mutex_);
    progressed_.wait(lock, [&] { return outstanding_.empty() && holds_ == 0; });
}

void Dispatcher::Hold() {
    std::lock_guard lock(mutex_);
    ++holds_;
}

void Dispatcher::Release() {
    std::lock_guard lock(mutex_);
    --holds_;
    progressed_.notify_all();
}

bool Dispatcher::OnDispatcherThread() const {
    std::lock_guard lock(mutex_);
    return started_ && std::this_thread::get_id() == thread_;
}

unsigned long Dispatcher::ThreadIdent() const {
    std::lock_guard lock(mutex_);
    return ident_;
}

void Dispatcher::Run(py::object& task) {
    try {
        task();
    } catch (py::error_already_set& error) {
        // A handler's error is reported on the standard error, as Painter logs it; the delivery of
        // the other handlers and of later events goes on.
        error.restore();
        PyErr_Print();
    } catch (const std::exception& error) {
        PySys_WriteStderr("dispatcher task failed: %.900s\n", error.what());
    }
}

void Dispatcher::Finished(std::uint64_t seq) {
    std::lock_guard lock(mutex_);
    outstanding_.erase(seq);
    progressed_.notify_all();
}

void Dispatcher::Work() {
    {
        std::lock_guard lock(mutex_);
        thread_ = std::this_thread::get_id();
        ident_ = PyThread_get_thread_ident();
    }
    for (;;) {
        std::pair<std::uint64_t, py::object> task;
        {
            std::unique_lock lock(mutex_);
            queued_.wait(lock, [this] { return !queue_.empty(); });
            task = std::move(queue_.front());
            queue_.pop_front();
        }
        {
            py::gil_scoped_acquire gil;
            Run(task.second);
            task.second = py::object();
        }
        Finished(task.first);
    }
}

}  // namespace uzp::python
