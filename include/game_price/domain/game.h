#pragma once

#include "game_price/domain/domain_types.h"

#include <string>
#include <vector>

namespace game_price {

struct Game {
    std::string id;
    std::string title;
    std::string normalizedTitle;
    std::vector<Platform> supportedPlatforms;
};

}  // namespace game_price
