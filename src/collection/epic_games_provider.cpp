#include "game_price/collection/epic_games_provider.h"

#include "game_price/support/text_utils.h"

#include <fstream>
#include <map>
#include <stdexcept>

namespace game_price {
namespace {

Currency parseProviderCurrency(const std::string& value) {
    if (value == "KRW") return Currency::KRW;
    if (value == "USD") return Currency::USD;
    if (value == "EUR") return Currency::EUR;
    if (value == "GBP") return Currency::GBP;
    if (value == "JPY") return Currency::JPY;
    throw std::runtime_error("unsupported currency");
}

}  // namespace

EpicGamesProvider::EpicGamesProvider(const std::string& dataPath, Store store)
    : store_(store) {
    if (store != Store::EpicGamesStore && store != Store::UbisoftStore &&
        store != Store::GOG && store != Store::MetaQuestStore &&
        store != Store::EAApp && store != Store::BattleNet) {
        throw std::invalid_argument("unsupported PC storefront provider");
    }
    std::ifstream input(dataPath);
    if (!input) throw std::runtime_error("Cannot open Epic Games data: " + dataPath);

    std::map<std::string, std::string> fields;
    const auto appendProduct = [&]() {
        if (fields.empty()) return;
        try {
            const auto regularKey = fields.count("regular_price_minor")
                ? "regular_price_minor" : "regular_price_krw";
            const auto currentKey = fields.count("current_price_minor")
                ? "current_price_minor" : "current_price_krw";
            const auto regularPrice = std::stoll(fields.at(regularKey));
            const auto currentPrice = std::stoll(fields.at(currentKey));
            const auto currency = parseProviderCurrency(
                fields.count("currency") ? fields.at("currency") : "KRW");
            const auto discount = std::stoi(fields.at("discount_percent"));
            if (regularPrice < currentPrice || currentPrice < 0 ||
                discount < 0 || discount > 100) {
                throw std::runtime_error("invalid price");
            }
            for (const auto& os : split(fields.at("compatible_os"), '|')) {
                if (os != "WIN" && os != "MAC" && os != "LINUX" &&
                    os != "META") {
                    throw std::runtime_error("unsupported operating system");
                }
            }
            products_.push_back(RawProduct{
                fields.at("offer_id"), fields.at("game_id"), regularPrice,
                currentPrice, currency, discount, fields.at("compatible_os"),
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
    return store_;
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
            else if (os == "LINUX") platforms.push_back(Platform::Linux);
            else if (os == "META") platforms.push_back(Platform::MetaQuest);
        }
        result.push_back(StoreProduct{
            raw.offerId, raw.gameId, store_, std::move(platforms),
            Money{raw.currentPriceMinor, raw.currency}, raw.active, std::nullopt,
            Money{raw.regularPriceMinor, raw.currency}, raw.discountPercent,
            Region::KR, GameEdition::Standard, OfferType::BaseGame});
    }
    return result;
}

}  // namespace game_price
