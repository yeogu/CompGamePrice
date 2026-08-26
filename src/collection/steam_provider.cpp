#include "game_price/collection/steam_provider.h"

#include "game_price/support/text_utils.h"

#include <fstream>
#include <stdexcept>

namespace game_price {

SteamProvider::SteamProvider(const std::string& dataPath) {
    std::ifstream input(dataPath);
    if (!input) {
        throw std::runtime_error("Cannot open Steam data: " + dataPath);
    }

    std::string line;
    while (std::getline(input, line)) {
        if (trim(line).empty() || line.front() == '#') {
            continue;
        }
        const auto fields = split(line, '|');
        if (fields.size() != 5 && fields.size() != 6 && fields.size() != 8) {
            throw std::runtime_error("Invalid Steam row: " + line);
        }
        if (fields.size() == 8) {
            products_.push_back(RawProduct{
                fields[0], fields[1], std::stoll(fields[2]), std::stoll(fields[3]),
                std::stoi(fields[4]), fields[5], parseBool(fields[6]), fields[7]});
        } else {
            products_.push_back(RawProduct{
                fields[0], fields[1], std::nullopt, std::stoll(fields[2]), 0,
                fields[3], parseBool(fields[4]),
                fields.size() == 6
                    ? std::optional<std::string>{fields[5]}
                    : std::nullopt});
        }
    }
}

Store SteamProvider::store() const noexcept {
    return Store::Steam;
}

std::vector<StoreProduct> SteamProvider::findProducts(const std::string& gameId) const {
    std::vector<StoreProduct> result;
    for (const auto& raw : products_) {
        if (raw.gameId != gameId) {
            continue;
        }

        std::vector<Platform> platforms;
        for (const auto& flag : split(raw.platformFlags, ',')) {
            if (flag == "windows") platforms.push_back(Platform::Windows);
            else if (flag == "mac") platforms.push_back(Platform::MacOS);
            else if (flag == "linux") platforms.push_back(Platform::Linux);
        }

        result.push_back(StoreProduct{
            raw.appId, raw.gameId, Store::Steam, std::move(platforms),
            Money{raw.finalPriceWon, Currency::KRW}, raw.available, raw.observedAt,
            raw.regularPriceWon
                ? std::optional<Money>{Money{*raw.regularPriceWon, Currency::KRW}}
                : std::nullopt,
            raw.discountPercent, Region::KR, GameEdition::Standard,
            OfferType::BaseGame});
    }
    return result;
}

}  // namespace game_price
