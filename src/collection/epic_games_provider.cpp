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
            for (const auto& os : split(fields.at("compatible_os"), '|')) {
                if (os != "WIN" && os != "MAC") {
                    throw std::runtime_error("unsupported operating system");
                }
            }
            products_.push_back(RawProduct{
                fields.at("offer_id"), fields.at("game_id"), regularPrice,
                currentPrice, discount, fields.at("compatible_os"),
                fields.at("status") == "ACTIVE"});
        } catch (const std::exception& error) {
            rejections_.push_back(ProviderRejection{
                fields.count("game_id") ? fields.at("game_id") : "",
                fields.count("offer_id") ? fields.at("offer_id") : "",
                "Invalid Epic Games product block: " + std::string(error.what())});
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
            rejections_.push_back(ProviderRejection{
                fields.count("game_id") ? fields.at("game_id") : "",
                fields.count("offer_id") ? fields.at("offer_id") : "",
                "Invalid Epic Games row: missing separator"});
            continue;
        }
        fields[trim(line.substr(0, separator))] = trim(line.substr(separator + 1));
    }
    appendProduct();
}

std::vector<ProviderRejection> EpicGamesProvider::findRejections(
    const std::string& gameId) const {
    std::vector<ProviderRejection> result;
    for (const auto& rejection : rejections_) {
        if (rejection.gameId == gameId) result.push_back(rejection);
    }
    return result;
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
            Money{raw.regularPriceWon, Currency::KRW}, raw.discountPercent,
            Region::KR, GameEdition::Standard, OfferType::BaseGame});
    }
    return result;
}

}  // namespace game_price
