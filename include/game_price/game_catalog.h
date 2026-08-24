#pragma once

#include "game_price/game.h"

#include <optional>
#include <string>
#include <vector>

namespace game_price {

class GameCatalog {
public:
    explicit GameCatalog(const std::string& dataPath);

    std::optional<Game> findByName(const std::string& name) const;

private:
    std::vector<Game> games_;
};

}  // namespace game_price
