#include "game_price/catalog/game_catalog.h"

#include "game_price/support/text_utils.h"

#include <fstream>
#include <stdexcept>

namespace game_price {

GameCatalog::GameCatalog(const std::string& dataPath) {
    std::ifstream input(dataPath);
    if (!input) {
        throw std::runtime_error("Cannot open game catalog: " + dataPath);
    }

    std::string line;
    while (std::getline(input, line)) {
        if (trim(line).empty() || line.front() == '#') {
            continue;
        }
        const auto fields = split(line, '|');
        if (fields.size() != 2) {
            throw std::runtime_error("Invalid game catalog row: " + line);
        }
        games_.push_back(Game{fields[0], fields[1], normalizeName(fields[1])});
    }
}

std::optional<Game> GameCatalog::findByName(const std::string& name) const {
    const auto normalized = normalizeName(name);
    const auto found = std::find_if(games_.begin(), games_.end(), [&](const Game& game) {
        return game.normalizedTitle == normalized;
    });
    return found == games_.end() ? std::nullopt : std::optional<Game>{*found};
}

}  // namespace game_price
