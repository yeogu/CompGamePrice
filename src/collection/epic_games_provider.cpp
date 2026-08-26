#include "game_price/collection/epic_games_provider.h"

#include "game_price/support/text_utils.h"

#include <fstream>
#include <map>
#include <stdexcept>

namespace game_price {

EpicGamesProvider::EpicGamesProvider(const std::string& dataPath) {
    std::ifstream input(dataPath);
    if (!input) throw std::runtime_error("Cannot open Epic Games data: " + dataPath);

    std::map<std::string, std::string> fields;
    const auto appendProduct = [&]() {
        if (fields.empty()) return;
        try {
            const auto regularPrice = std::stoll(fields.at("regular_price_krw"));
            const auto currentPrice = std::stoll(fields.at("current_price_krw"));
            const auto discount = std::stoi(fields.at("discount_percent"));
            if (regularPrice < currentPrice || currentPrice < 0 ||
                discount < 0 || discount > 100) {
                throw std::runtime_error("invalid price");
            }
            products_.push_back(RawProduct{
                fields.at("offer_id"), fields.at("game_id"), regularPrice,
                currentPrice, discount, fields.at("compatible_os"),
                fields.at("status") == "ACTIVE"});
        } catch (const std::exception&) {
            throw std::runtime_error("Invalid Epic Games product block");
        }
        fields.clear();
    };

    std::string line;
    while (std::getline(input, line)) {
        line = trim(line);
        if (line.empty()) {
            appendProduct();
            continue;
        }
        if (line.front() == '#') continue;
        const auto separator = line.find(':');
        if (separator == std::string::npos) {
            throw std::runtime_error("Invalid Epic Games row: " + line);
        }
        fields[trim(line.substr(0, separator))] = trim(line.substr(separator + 1));
    }
    appendProduct();
}

Store EpicGamesProvider::store() const noexcept {
    return Store::EpicGamesStore;
}

std::vector<StoreProduct> EpicGamesProvider::findProducts(
    const std::string& gameId) const {
    std::vector<StoreProduct> result;
    for (const auto& raw : products_) {
        if (raw.gameId != gameId) continue;
        std::vector<Platform> platforms;
        for (const auto& os : split(raw.compatibleOs, '|')) {
            if (os == "WIN") platforms.push_back(Platform::Windows);
            else if (os == "MAC") platforms.push_back(Platform::MacOS);
        }
        result.push_back(StoreProduct{
            raw.offerId, raw.gameId, Store::EpicGamesStore, std::move(platforms),
            Money{raw.currentPriceWon, Currency::KRW}, raw.active, std::nullopt,
            Money{raw.regularPriceWon, Currency::KRW}, raw.discountPercent});
    }
    return result;
}

}  // namespace game_price
