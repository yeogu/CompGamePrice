#pragma once

#include <string>

struct sqlite3;

namespace game_price {

class Database {
public:
    explicit Database(const std::string& path);
    ~Database();

    Database(const Database&) = delete;
    Database& operator=(const Database&) = delete;

    sqlite3* handle() const noexcept;
    void execute(const std::string& sql) const;

private:
    sqlite3* handle_{nullptr};
};

}  // namespace game_price
