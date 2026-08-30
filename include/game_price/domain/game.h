#pragma once

#include "game_price/domain/domain_types.h"

#include <string>
#include <utility>
#include <vector>

namespace game_price {

struct Game {
    Game(
        std::string gameId,
        std::string gameTitle,
        std::string normalizedGameTitle,
        std::vector<Platform> platforms,
        std::vector<std::string> gameGenres = {},
        std::vector<std::string> gameTags = {})
        : id(std::move(gameId)),
          title(std::move(gameTitle)),
          normalizedTitle(std::move(normalizedGameTitle)),
          supportedPlatforms(std::move(platforms)),
          genres(std::move(gameGenres)),
          tags(std::move(gameTags)) {}

    std::string id;
    std::string title;
    std::string normalizedTitle;
    std::vector<Platform> supportedPlatforms;
    std::vector<std::string> genres;
    std::vector<std::string> tags;
};

}  // namespace game_price
