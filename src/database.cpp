#include "game_price/database.h"

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

}  // namespace game_price
