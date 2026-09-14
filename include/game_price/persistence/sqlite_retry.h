#pragma once

#include <sqlite3.h>

#include <chrono>
#include <thread>

namespace game_price {

inline constexpr int SqliteBusyTimeoutMilliseconds = 30000;
inline constexpr int SqliteLockRetryCount = 4;

inline bool isSqliteLockError(int result) noexcept {
    const int primaryResult = result & 0xff;
    return primaryResult == SQLITE_BUSY || primaryResult == SQLITE_LOCKED;
}

inline void waitForSqliteLockRetry(int retryIndex) {
    const auto delay = std::chrono::milliseconds(100 * (1 << retryIndex));
    std::this_thread::sleep_for(delay);
}

}  // namespace game_price
