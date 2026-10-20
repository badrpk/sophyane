#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <sqlite3.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
constexpr std::size_t kCapacity = 1u << 16;
constexpr std::size_t kMaxPayload = 1024;

struct Event {
    std::uint64_t sequence;
    std::int64_t born_ns;
    std::int64_t value;
    std::uint32_t payload_size;
    char payload[kMaxPayload];
};

struct Cell {
    std::atomic<std::size_t> turn;
    Event event{};
};

class Ring final {
    std::atomic<std::size_t> enqueue_{0};
    std::atomic<std::size_t> dequeue_{0};
    std::vector<Cell> cells_;

public:
    Ring() : cells_(kCapacity) {
        for (std::size_t i = 0; i < kCapacity; ++i) {
            cells_[i].turn.store(i, std::memory_order_relaxed);
        }
    }

    bool push(const Event& event) noexcept {
        std::size_t position = enqueue_.load(std::memory_order_relaxed);
        for (;;) {
            Cell& cell = cells_[position & (kCapacity - 1)];
            const std::size_t turn = cell.turn.load(std::memory_order_acquire);
            const std::intptr_t difference =
                static_cast<std::intptr_t>(turn) - static_cast<std::intptr_t>(position);
            if (difference == 0) {
                if (enqueue_.compare_exchange_weak(
                        position, position + 1, std::memory_order_relaxed)) {
                    cell.event = event;
                    cell.turn.store(position + 1, std::memory_order_release);
                    return true;
                }
            } else if (difference < 0) {
                return false;
            } else {
                position = enqueue_.load(std::memory_order_relaxed);
            }
        }
    }

    bool pop(Event& event) noexcept {
        std::size_t position = dequeue_.load(std::memory_order_relaxed);
        for (;;) {
            Cell& cell = cells_[position & (kCapacity - 1)];
            const std::size_t turn = cell.turn.load(std::memory_order_acquire);
            const std::intptr_t difference = static_cast<std::intptr_t>(turn) -
                static_cast<std::intptr_t>(position + 1);
            if (difference == 0) {
                if (dequeue_.compare_exchange_weak(
                        position, position + 1, std::memory_order_relaxed)) {
                    event = cell.event;
                    cell.turn.store(position + kCapacity, std::memory_order_release);
                    return true;
                }
            } else if (difference < 0) {
                return false;
            } else {
                position = dequeue_.load(std::memory_order_relaxed);
            }
        }
    }
};

static std::int64_t clock_ns() noexcept {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

static std::string sqlite_message(sqlite3* db, int rc) {
    return db ? sqlite3_errmsg(db) : sqlite3_errstr(rc);
}

class Database final {
    sqlite3* db_ = nullptr;

public:
    explicit Database(const char* path) {
        const int rc = sqlite3_open_v2(
            path, &db_, SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
            nullptr);
        if (rc != SQLITE_OK) {
            const std::string message = sqlite_message(db_, rc);
            if (db_) sqlite3_close(db_);
            db_ = nullptr;
            throw std::runtime_error("sqlite open failed: " + message);
        }
    }

    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;
    ~Database() { if (db_) sqlite3_close(db_); }
    sqlite3* get() const noexcept { return db_; }

    void exec(const char* sql) {
        char* error = nullptr;
        const int rc = sqlite3_exec(db_, sql, nullptr, nullptr, &error);
        if (rc != SQLITE_OK) {
            const std::string message = error ? error : sqlite_message(db_, rc);
            if (error) sqlite3_free(error);
            throw std::runtime_error(message);
        }
    }
};

class Statement final {
    sqlite3_stmt* statement_ = nullptr;

public:
    Statement() = default;
    Statement(const Statement&) = delete;
    Statement& operator=(const Statement&) = delete;
    ~Statement() { if (statement_) sqlite3_finalize(statement_); }

    void prepare(sqlite3* db, const char* sql) {
        const int rc = sqlite3_prepare_v2(db, sql, -1, &statement_, nullptr);
        if (rc != SQLITE_OK) throw std::runtime_error(sqlite_message(db, rc));
    }

    sqlite3_stmt* get() const noexcept { return statement_; }
};

class Transaction final {
    sqlite3* db_;
    std::atomic<std::uint64_t>* rollback_failures_;
    bool active_ = true;

public:
    Transaction(sqlite3* db, std::atomic<std::uint64_t>* rollback_failures)
        : db_(db), rollback_failures_(rollback_failures) {
        const int rc = sqlite3_exec(db_, "BEGIN IMMEDIATE", nullptr, nullptr, nullptr);
        if (rc != SQLITE_OK) throw std::runtime_error(sqlite_message(db_, rc));
    }

    Transaction(const Transaction&) = delete;
    Transaction& operator=(const Transaction&) = delete;

    void commit() {
        const int rc = sqlite3_exec(db_, "COMMIT", nullptr, nullptr, nullptr);
        if (rc != SQLITE_OK) throw std::runtime_error(sqlite_message(db_, rc));
        active_ = false;
    }

    ~Transaction() {
        if (!active_) return;
        const int rc = sqlite3_exec(db_, "ROLLBACK", nullptr, nullptr, nullptr);
        if (rc != SQLITE_OK && rollback_failures_) {
            rollback_failures_->fetch_add(1, std::memory_order_relaxed);
        }
    }
};

class Reconciler final {
    Database db_;
    Ring ring_;
    std::atomic<bool> accepting_{true};
    std::thread worker_;
    std::atomic<std::uint64_t> accepted_{0};
    std::atomic<std::uint64_t> written_{0};
    std::atomic<std::uint64_t> committed_{0};
    std::atomic<std::uint64_t> rejected_{0};
    std::atomic<std::uint64_t> failed_{0};
    std::atomic<std::uint64_t> cleanup_failures_{0};
    std::atomic<std::uint64_t> rollback_failures_{0};
    std::atomic<std::uint64_t> commit_latency_total_ns_{0};
    std::atomic<std::uint64_t> commit_latency_count_{0};
    mutable std::mutex latency_mutex_;
    std::vector<std::uint64_t> commit_latencies_ns_;
    std::mutex admission_mutex_;
    std::mutex close_mutex_;

    void fail_queued_events() noexcept {
        Event ignored{};
        while (ring_.pop(ignored)) {
            failed_.fetch_add(1, std::memory_order_relaxed);
        }
    }

    void consume() noexcept {
        Statement insert;
        try {
            insert.prepare(db_.get(),
                "INSERT OR REPLACE INTO reconciled_events"
                "(sequence,timestamp_ns,value,payload) VALUES(?,?,?,?)");
        } catch (...) {
            accepting_.store(false, std::memory_order_release);
            fail_queued_events();
            return;
        }

        Event event{};
        for (;;) {
            if (ring_.pop(event)) {
                try {
                    Transaction transaction(db_.get(), &rollback_failures_);
                    int rc = sqlite3_bind_int64(
                        insert.get(), 1, static_cast<sqlite3_int64>(event.sequence));
                    if (rc != SQLITE_OK) throw std::runtime_error(sqlite_message(db_.get(), rc));
                    rc = sqlite3_bind_int64(
                        insert.get(), 2, static_cast<sqlite3_int64>(event.born_ns));
                    if (rc != SQLITE_OK) throw std::runtime_error(sqlite_message(db_.get(), rc));
                    rc = sqlite3_bind_int64(
                        insert.get(), 3, static_cast<sqlite3_int64>(event.value));
                    if (rc != SQLITE_OK) throw std::runtime_error(sqlite_message(db_.get(), rc));
                    rc = sqlite3_bind_blob(
                        insert.get(), 4, event.payload,
                        static_cast<int>(event.payload_size), SQLITE_TRANSIENT);
                    if (rc != SQLITE_OK) throw std::runtime_error(sqlite_message(db_.get(), rc));

                    const auto started = std::chrono::steady_clock::now();
                    rc = sqlite3_step(insert.get());
                    if (rc != SQLITE_DONE) throw std::runtime_error(sqlite_message(db_.get(), rc));
                    // written means sqlite3_step completed inside the transaction;
                    // committed is incremented only after COMMIT succeeds.
                    written_.fetch_add(1, std::memory_order_relaxed);
                    transaction.commit();
                    const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
                        std::chrono::steady_clock::now() - started).count();
                    commit_latency_total_ns_.fetch_add(
                        static_cast<std::uint64_t>(elapsed), std::memory_order_relaxed);
                    commit_latency_count_.fetch_add(1, std::memory_order_relaxed);
                    {
                        std::lock_guard<std::mutex> lock(latency_mutex_);
                        commit_latencies_ns_.push_back(static_cast<std::uint64_t>(elapsed));
                    }
                    committed_.fetch_add(1, std::memory_order_relaxed);
                } catch (...) {
                    failed_.fetch_add(1, std::memory_order_relaxed);
                    accepting_.store(false, std::memory_order_release);
                    fail_queued_events();
                    return;
                }
                int cleanup_rc = sqlite3_reset(insert.get());
                if (cleanup_rc != SQLITE_OK) {
                    cleanup_failures_.fetch_add(1, std::memory_order_relaxed);
                    accepting_.store(false, std::memory_order_release);
                    fail_queued_events();
                    return;
                }
                cleanup_rc = sqlite3_clear_bindings(insert.get());
                if (cleanup_rc != SQLITE_OK) {
                    cleanup_failures_.fetch_add(1, std::memory_order_relaxed);
                    accepting_.store(false, std::memory_order_release);
                    fail_queued_events();
                    return;
                }
                continue;
            }
            if (!accepting_.load(std::memory_order_acquire)) return;
            std::this_thread::yield();
        }
    }

public:
    explicit Reconciler(const char* path) : db_(path) {
        db_.exec("PRAGMA journal_mode=WAL");
        db_.exec("PRAGMA synchronous=NORMAL");
        db_.exec(
            "CREATE TABLE IF NOT EXISTS reconciled_events("
            "sequence INTEGER PRIMARY KEY,timestamp_ns INTEGER NOT NULL,"
            "value INTEGER NOT NULL,payload BLOB NOT NULL)");
        worker_ = std::thread(&Reconciler::consume, this);
    }

    ~Reconciler() { close(); }

    bool submit(std::uint64_t sequence, std::int64_t value,
                const char* payload, std::size_t size) noexcept {
        std::lock_guard<std::mutex> lock(admission_mutex_);
        if (size > kMaxPayload || (size != 0 && payload == nullptr) ||
            !accepting_.load(std::memory_order_acquire)) {
            rejected_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        Event event{};
        event.sequence = sequence;
        event.born_ns = clock_ns();
        event.value = value;
        event.payload_size = static_cast<std::uint32_t>(size);
        if (size) std::memcpy(event.payload, payload, size);
        if (!ring_.push(event)) {
            rejected_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        accepted_.fetch_add(1, std::memory_order_relaxed);
        return true;
    }

    void close() noexcept {
        std::lock_guard<std::mutex> close_lock(close_mutex_);
        {
            std::lock_guard<std::mutex> admission_lock(admission_mutex_);
            accepting_.store(false, std::memory_order_release);
        }
        if (worker_.joinable()) worker_.join();
    }

    PyObject* stats() const {
        PyObject* result = PyDict_New();
        if (!result) return nullptr;
        const auto put = [result](const char* name, std::uint64_t value) {
            PyObject* item = PyLong_FromUnsignedLongLong(value);
            if (!item) return -1;
            const int rc = PyDict_SetItemString(result, name, item);
            Py_DECREF(item);
            return rc;
        };
        if (put("accepted", accepted_.load(std::memory_order_relaxed)) < 0 ||
            put("written", written_.load(std::memory_order_relaxed)) < 0 ||
            put("committed", committed_.load(std::memory_order_relaxed)) < 0 ||
            put("rejected", rejected_.load(std::memory_order_relaxed)) < 0 ||
            put("failed", failed_.load(std::memory_order_relaxed)) < 0 ||
            put("cleanup_failures", cleanup_failures_.load(std::memory_order_relaxed)) < 0 ||
            put("rollback_failures", rollback_failures_.load(std::memory_order_relaxed)) < 0 ||
            put("commit_latency_count", commit_latency_count_.load(std::memory_order_relaxed)) < 0 ||
            put("commit_latency_total_ns", commit_latency_total_ns_.load(std::memory_order_relaxed)) < 0) {
            Py_DECREF(result);
            return nullptr;
        }
        {
            std::lock_guard<std::mutex> lock(latency_mutex_);
            PyObject* latencies = PyTuple_New(static_cast<Py_ssize_t>(commit_latencies_ns_.size()));
            if (!latencies) {
                Py_DECREF(result);
                return nullptr;
            }
            for (std::size_t i = 0; i < commit_latencies_ns_.size(); ++i) {
                PyObject* item = PyLong_FromUnsignedLongLong(commit_latencies_ns_[i]);
                if (!item) {
                    Py_DECREF(latencies);
                    Py_DECREF(result);
                    return nullptr;
                }
                PyTuple_SET_ITEM(latencies, static_cast<Py_ssize_t>(i), item);
            }
            if (PyDict_SetItemString(result, "commit_latencies_ns", latencies) < 0) {
                Py_DECREF(latencies);
                Py_DECREF(result);
                return nullptr;
            }
            Py_DECREF(latencies);
        }
        return result;
    }
};

struct PyReconciler { PyObject_HEAD Reconciler* impl = nullptr; };

int init(PyReconciler* self, PyObject* args, PyObject* kwargs) {
    const char* path = "shmry_economy.db";
    static char* names[] = {const_cast<char*>("path"), nullptr};
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|s", names, &path)) return -1;
    try {
        self->impl = new Reconciler(path);
    } catch (const std::exception& error) {
        PyErr_SetString(PyExc_RuntimeError, error.what());
        return -1;
    }
    return 0;
}

void dealloc(PyReconciler* self) {
    delete self->impl;
    Py_TYPE(self)->tp_free(reinterpret_cast<PyObject*>(self));
}

PyObject* submit(PyReconciler* self, PyObject* args) {
    unsigned long long sequence;
    long long value;
    const char* payload = nullptr;
    Py_ssize_t size = 0;
    if (!PyArg_ParseTuple(args, "KL|y#", &sequence, &value, &payload, &size)) return nullptr;
    bool accepted;
    Py_BEGIN_ALLOW_THREADS
    accepted = self->impl->submit(
        static_cast<std::uint64_t>(sequence), static_cast<std::int64_t>(value),
        payload, static_cast<std::size_t>(size));
    Py_END_ALLOW_THREADS
    if (accepted) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PyObject* close_reconciler(PyReconciler* self, PyObject*) {
    Py_BEGIN_ALLOW_THREADS
    self->impl->close();
    Py_END_ALLOW_THREADS
    Py_RETURN_NONE;
}

PyObject* stats(PyReconciler* self, PyObject*) { return self->impl->stats(); }

PyMethodDef methods[] = {
    {"submit", reinterpret_cast<PyCFunction>(submit), METH_VARARGS, nullptr},
    {"close", reinterpret_cast<PyCFunction>(close_reconciler), METH_NOARGS, nullptr},
    {"stats", reinterpret_cast<PyCFunction>(stats), METH_NOARGS, nullptr},
    {nullptr, nullptr, 0, nullptr},
};
PyTypeObject type = {PyVarObject_HEAD_INIT(nullptr, 0)};
PyModuleDef module = {PyModuleDef_HEAD_INIT, "_reconciler", nullptr, -1, nullptr};
}  // namespace

PyMODINIT_FUNC PyInit__reconciler() {
    type.tp_name = "sophyane.native._reconciler.Reconciler";
    type.tp_basicsize = sizeof(PyReconciler);
    type.tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE;
    type.tp_new = PyType_GenericNew;
    type.tp_init = reinterpret_cast<initproc>(init);
    type.tp_dealloc = reinterpret_cast<destructor>(dealloc);
    type.tp_methods = methods;
    if (PyType_Ready(&type) < 0) return nullptr;
    PyObject* module_object = PyModule_Create(&module);
    if (!module_object) return nullptr;
    Py_INCREF(&type);
    if (PyModule_AddObject(
            module_object, "Reconciler", reinterpret_cast<PyObject*>(&type)) < 0) {
        Py_DECREF(&type);
        Py_DECREF(module_object);
        return nullptr;
    }
    return module_object;
}
