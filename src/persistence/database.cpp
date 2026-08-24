#include "game_price/persistence/database.h"

#include <sqlite3.h>

#include <stdexcept>

namespace game_price {

Database::Database(const std::string& path) {
    const int result = sqlite3_open(path.c_str(), &handle_);
    if (result != SQLITE_OK) {
        const std::string message = handle_ ? sqlite3_errmsg(handle_) : "unknown error";
        if (handle_) {
            sqlite3_close(handle_);
            handle_ = nullptr;
        }
        throw std::runtime_error("Cannot open SQLite database: " + message);
    }
    execute("PRAGMA foreign_keys = ON;");
}

Database::~Database() {
    if (handle_) {
        sqlite3_close(handle_);
    }
}

sqlite3* Database::handle() const noexcept {
    return handle_;
}

void Database::execute(const std::string& sql) const {
    char* errorMessage = nullptr;
    const int result = sqlite3_exec(handle_, sql.c_str(), nullptr, nullptr, &errorMessage);
    if (result != SQLITE_OK) {
        const std::string message = errorMessage ? errorMessage : "unknown error";
        sqlite3_free(errorMessage);
        throw std::runtime_error("SQLite error: " + message);
    }
}

int Database::userVersion() const {
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(handle_, "PRAGMA user_version;", -1, &statement, nullptr) !=
        SQLITE_OK) {
        throw std::runtime_error(
            "Cannot read SQLite schema version: " + std::string(sqlite3_errmsg(handle_)));
    }

    const int result = sqlite3_step(statement);
    if (result != SQLITE_ROW) {
        sqlite3_finalize(statement);
        throw std::runtime_error(
            "Cannot read SQLite schema version: " + std::string(sqlite3_errmsg(handle_)));
    }
    const int version = sqlite3_column_int(statement, 0);
    sqlite3_finalize(statement);
    return version;
}

}  // namespace game_price
