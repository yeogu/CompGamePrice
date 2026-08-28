#include "game_price/collection/google_play_provider.h"

#include "game_price/support/text_utils.h"

#include <fstream>
#include <map>
#include <stdexcept>

namespace game_price {

GooglePlayProvider::GooglePlayProvider(const std::string& dataPath) {
    std::ifstream input(dataPath);
    if (!input) {
        throw std::runtime_error("Cannot open Google Play data: " + dataPath);
    }

    std::map<std::string, std::string> fields;
    auto appendProduct = [&]() {
        if (fields.empty()) return;
        try {
            const auto priceMicros = std::stoll(fields.at("price_micros"));
            constexpr std::int64_t microsPerWon = 1'000'000;
            if (priceMicros < 0 || priceMicros % microsPerWon != 0) {
                throw std::runtime_error("invalid KRW micros");
            }
            products_.push_back(RawProduct{
                fields.at("package_name"), fields.at("game_id"),
                priceMicros, parseBool(fields.at("published"))});
        } catch (const std::exception&) {
            throw std::runtime_error("Invalid Google Play product block");
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
        const auto separator = line.find('=');
        if (separator == std::string::npos) {
            throw std::runtime_error("Invalid Google Play row: " + line);
        }
        fields[trim(line.substr(0, separator))] = trim(line.substr(separator + 1));
    }
    appendProduct();
}

Store GooglePlayProvider::store() const noexcept {
    return Store::GooglePlay;
}

std::vector<StoreProduct> GooglePlayProvider::findProducts(const std::string& gameId) const {
    std::vector<StoreProduct> result;
    for (const auto& raw : products_) {
        if (raw.gameId == gameId) {
            constexpr std::int64_t microsPerWon = 1'000'000;
            result.push_back(StoreProduct{
                raw.packageName, raw.gameId, Store::GooglePlay, {Platform::Android},
                Money{raw.priceMicros / microsPerWon, Currency::KRW}, raw.published,
                std::nullopt, std::nullopt, 0, Region::KR,
                GameEdition::Standard, OfferType::BaseGame});
        }
    }
    return result;
}

}  // namespace game_price
