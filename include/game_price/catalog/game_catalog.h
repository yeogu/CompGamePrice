#pragma once

#include "game_price/domain/game.h"

#include <optional>
#include <string>
#include <vector>

namespace game_price {

class GameCatalog {
public:
    explicit GameCatalog(const std::string& dataPath);

    std::optional<Game> findByName(const std::string& name) const;
    std::optional<Game> findById(const std::string& id) const;
    std::vector<Game> searchByName(const std::string& query) const;

private:
    std::vector<Game> games_;
};

}  // namespace game_price
