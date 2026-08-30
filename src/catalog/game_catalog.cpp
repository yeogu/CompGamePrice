#include "game_price/catalog/game_catalog.h"

#include "game_price/persistence/database.h"
#include "game_price/support/text_utils.h"

#include <sqlite3.h>

#include <algorithm>
#include <fstream>
#include <iterator>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>

namespace game_price {
namespace {

class Statement {
public:
    Statement(sqlite3* database, const char* sql) : database_(database) {
        if (sqlite3_prepare_v2(database, sql, -1, &statement_, nullptr) != SQLITE_OK) {
            throw std::runtime_error(
                "Cannot prepare Game Catalog JSON query: " +
                std::string(sqlite3_errmsg(database)));
        }
    }

    ~Statement() { sqlite3_finalize(statement_); }
    Statement(const Statement&) = delete;
    Statement& operator=(const Statement&) = delete;

    void bindJson(const std::string& json) {
        if (sqlite3_bind_text(
                statement_, 1, json.c_str(), -1, SQLITE_TRANSIENT) != SQLITE_OK) {
            throw std::runtime_error("Cannot bind Game Catalog JSON");
        }
    }

    bool next() {
        const int result = sqlite3_step(statement_);
        if (result == SQLITE_ROW) return true;
        if (result == SQLITE_DONE) return false;
        throw std::runtime_error(
            "Cannot parse Game Catalog JSON: " +
            std::string(sqlite3_errmsg(database_)));
    }

    int integer(int column) const { return sqlite3_column_int(statement_, column); }

    std::optional<std::string> optionalText(int column) const {
        if (sqlite3_column_type(statement_, column) == SQLITE_NULL) return std::nullopt;
        const auto* value = sqlite3_column_text(statement_, column);
        return value
            ? std::optional<std::string>{reinterpret_cast<const char*>(value)}
            : std::nullopt;
    }

private:
    sqlite3* database_;
    sqlite3_stmt* statement_{nullptr};
};

std::string readFile(const std::string& path) {
    std::ifstream input(path);
    if (!input) throw std::runtime_error("Cannot open game catalog: " + path);
    return std::string(
        std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
}

void requireJsonString(
    const std::optional<std::string>& value,
    const std::optional<std::string>& type,
    const std::string& field) {
    if (!value || value->empty() || type != std::optional<std::string>{"text"}) {
        throw std::runtime_error("Game Catalog requires non-empty string " + field);
    }
}

Platform platformFromString(const std::string& value) {
    if (value == "Windows") return Platform::Windows;
    if (value == "macOS") return Platform::MacOS;
    if (value == "Linux") return Platform::Linux;
    if (value == "Android") return Platform::Android;
    if (value == "iOS") return Platform::IOS;
    if (value == "iPadOS") return Platform::IPadOS;
    if (value == "NintendoSwitch") return Platform::NintendoSwitch;
    if (value == "NintendoSwitch2") return Platform::NintendoSwitch2;
    throw std::runtime_error("Unsupported Game Catalog platform: " + value);
}

Store storeFromString(const std::string& value) {
    if (value == "Steam") return Store::Steam;
    if (value == "EpicGamesStore") return Store::EpicGamesStore;
    if (value == "NintendoEShop") return Store::NintendoEShop;
    if (value == "GooglePlay") return Store::GooglePlay;
    if (value == "AppleAppStore") return Store::AppleAppStore;
    throw std::runtime_error("Unsupported Game Catalog Store: " + value);
}

Region regionFromString(const std::string& value) {
    if (value == "KR") return Region::KR;
    throw std::runtime_error("Unsupported Game Catalog region: " + value);
}

GameEdition editionFromString(const std::string& value) {
    if (value == "Standard") return GameEdition::Standard;
    if (value == "Deluxe") return GameEdition::Deluxe;
    if (value == "Switch2Edition") return GameEdition::Switch2Edition;
    throw std::runtime_error("Unsupported Game Catalog edition: " + value);
}

OfferType offerTypeFromString(const std::string& value) {
    if (value == "BaseGame") return OfferType::BaseGame;
    if (value == "DLC") return OfferType::DLC;
    if (value == "Bundle") return OfferType::Bundle;
    if (value == "Subscription") return OfferType::Subscription;
    if (value == "UpgradePack") return OfferType::UpgradePack;
    throw std::runtime_error("Unsupported Game Catalog offer type: " + value);
}

std::vector<Platform> parsePlatforms(
    sqlite3* database,
    const std::optional<std::string>& platformsJson,
    const std::optional<std::string>& platformsType) {
    if (!platformsJson || platformsType != std::optional<std::string>{"array"}) {
        throw std::runtime_error("Game Catalog requires games[].platforms array");
    }
    Statement platforms(database, "SELECT value, type FROM json_each(?1);");
    platforms.bindJson(*platformsJson);
    std::vector<Platform> result;
    while (platforms.next()) {
        const auto value = platforms.optionalText(0);
        requireJsonString(value, platforms.optionalText(1), "games[].platforms[]");
        const auto platform = platformFromString(*value);
        if (std::find(result.begin(), result.end(), platform) != result.end()) {
            throw std::runtime_error("Duplicate Game Catalog platform: " + *value);
        }
        result.push_back(platform);
    }
    if (result.empty()) {
        throw std::runtime_error("Game Catalog platforms array cannot be empty");
    }
    return result;
}

std::vector<std::string> parseOptionalStringArray(
    sqlite3* database,
    const std::optional<std::string>& valuesJson,
    const std::optional<std::string>& valuesType,
    const std::string& field) {
    if (!valuesJson && !valuesType) {
        return {};
    }
    if (!valuesJson || valuesType != std::optional<std::string>{"array"}) {
        throw std::runtime_error("Game Catalog " + field + " must be an array");
    }
    Statement values(database, "SELECT value, type FROM json_each(?1);");
    values.bindJson(*valuesJson);
    std::vector<std::string> result;
    while (values.next()) {
        const auto value = values.optionalText(0);
        requireJsonString(value, values.optionalText(1), field + "[]");
        if (std::find(result.begin(), result.end(), *value) != result.end()) {
            throw std::runtime_error(
                "Duplicate Game Catalog " + field + " value: " + *value);
        }
        result.push_back(*value);
    }
    return result;
}

CompatibilityStatus compatibilityStatusFromString(const std::string& value) {
    if (value == "Native") return CompatibilityStatus::Native;
    if (value == "Compatible") return CompatibilityStatus::Compatible;
    if (value == "Limited") return CompatibilityStatus::Limited;
    if (value == "Unsupported") return CompatibilityStatus::Unsupported;
    if (value == "Unknown") return CompatibilityStatus::Unknown;
    throw std::runtime_error("Unsupported compatibility status: " + value);
}

std::vector<PlatformCompatibility> parseCompatibility(
    sqlite3* database,
    const std::optional<std::string>& compatibilityJson,
    const std::optional<std::string>& compatibilityType) {
    if (!compatibilityJson && !compatibilityType) return {};
    if (!compatibilityJson ||
        compatibilityType != std::optional<std::string>{"array"}) {
        throw std::runtime_error("Game Catalog compatibility must be an array");
    }
    Statement entries(database, R"sql(
        SELECT json_extract(value, '$.platform'), json_type(value, '$.platform'),
               json_extract(value, '$.status'), json_type(value, '$.status')
        FROM json_each(?1);
    )sql");
    entries.bindJson(*compatibilityJson);
    std::vector<PlatformCompatibility> result;
    while (entries.next()) {
        const auto platformName = entries.optionalText(0);
        const auto statusName = entries.optionalText(2);
        requireJsonString(platformName, entries.optionalText(1), "compatibility[].platform");
        requireJsonString(statusName, entries.optionalText(3), "compatibility[].status");
        const auto platform = platformFromString(*platformName);
        if (std::any_of(result.begin(), result.end(), [platform](const auto& item) {
                return item.platform == platform;
            })) {
            throw std::runtime_error("Duplicate compatibility platform: " + *platformName);
        }
        result.push_back(PlatformCompatibility{
            platform, compatibilityStatusFromString(*statusName)});
    }
    return result;
}

}  // namespace

GameCatalog::GameCatalog(const std::string& dataPath) {
    const auto json = readFile(dataPath);
    Database parser(":memory:");

    Statement header(parser.handle(), R"sql(
        SELECT json_valid(?1),
               json_extract(?1, '$.schemaVersion'),
               json_type(?1, '$.schemaVersion'),
               json_type(?1, '$.games');
    )sql");
    header.bindJson(json);
    if (!header.next() || header.integer(0) != 1 || header.integer(1) != 4 ||
        header.optionalText(2) != std::optional<std::string>{"integer"} ||
        header.optionalText(3) != std::optional<std::string>{"array"}) {
        throw std::runtime_error(
            "Game Catalog must be valid JSON with schemaVersion 4 and games array");
    }

    Statement rows(parser.handle(), R"sql(
        SELECT json_extract(value, '$.id'), json_type(value, '$.id'),
               json_extract(value, '$.title'), json_type(value, '$.title'),
               json_extract(value, '$.platforms'), json_type(value, '$.platforms'),
               json_extract(value, '$.products'), json_type(value, '$.products'),
               json_extract(value, '$.genres'), json_type(value, '$.genres'),
               json_extract(value, '$.tags'), json_type(value, '$.tags'),
               json_extract(value, '$.aliases'), json_type(value, '$.aliases'),
               json_extract(value, '$.developers'), json_type(value, '$.developers'),
               json_extract(value, '$.publishers'), json_type(value, '$.publishers')
        FROM json_each(?1, '$.games');
    )sql");
    rows.bindJson(json);
    while (rows.next()) {
        const auto id = rows.optionalText(0);
        const auto title = rows.optionalText(2);
        requireJsonString(id, rows.optionalText(1), "games[].id");
        requireJsonString(title, rows.optionalText(3), "games[].title");
        const auto normalizedTitle = normalizeName(*title);
        if (normalizedTitle.empty()) {
            throw std::runtime_error("Game Catalog title cannot normalize to empty");
        }
        auto platforms = parsePlatforms(
            parser.handle(), rows.optionalText(4), rows.optionalText(5));
        auto genres = parseOptionalStringArray(
            parser.handle(), rows.optionalText(8), rows.optionalText(9), "games[].genres");
        auto tags = parseOptionalStringArray(
            parser.handle(), rows.optionalText(10), rows.optionalText(11), "games[].tags");
        auto aliases = parseOptionalStringArray(
            parser.handle(), rows.optionalText(12), rows.optionalText(13), "games[].aliases");
        auto developers = parseOptionalStringArray(
            parser.handle(), rows.optionalText(14), rows.optionalText(15), "games[].developers");
        auto publishers = parseOptionalStringArray(
            parser.handle(), rows.optionalText(16), rows.optionalText(17), "games[].publishers");
        std::vector<std::string> normalizedAliases;
        normalizedAliases.reserve(aliases.size());
        for (const auto& alias : aliases) {
            const auto normalizedAlias = normalizeName(alias);
            if (normalizedAlias.empty() || normalizedAlias == normalizedTitle ||
                std::find(
                    normalizedAliases.begin(),
                    normalizedAliases.end(),
                    normalizedAlias) != normalizedAliases.end()) {
                throw std::runtime_error("Invalid or duplicate Game Catalog alias: " + alias);
            }
            normalizedAliases.push_back(normalizedAlias);
        }
        const auto identityCollides = std::any_of(
            games_.begin(),
            games_.end(),
            [&](const Game& game) {
                if (game.id == *id || game.normalizedTitle == normalizedTitle) {
                    return true;
                }
                if (std::find(
                        game.normalizedAliases.begin(),
                        game.normalizedAliases.end(),
                        normalizedTitle) != game.normalizedAliases.end()) {
                    return true;
                }
                return std::any_of(
                    normalizedAliases.begin(),
                    normalizedAliases.end(),
                    [&](const auto& alias) {
                        return alias == game.normalizedTitle ||
                            std::find(
                                game.normalizedAliases.begin(),
                                game.normalizedAliases.end(),
                                alias) != game.normalizedAliases.end();
                    });
            });
        if (identityCollides) {
            throw std::runtime_error("Duplicate Game Catalog identity: " + *id);
        }
        games_.push_back(Game{
            *id,
            *title,
            normalizedTitle,
            std::move(platforms),
            std::move(genres),
            std::move(tags),
            std::move(aliases),
            std::move(normalizedAliases),
            std::move(developers),
            std::move(publishers)});

        const auto productsJson = rows.optionalText(6);
        if (!productsJson || rows.optionalText(7) != std::optional<std::string>{"array"}) {
            throw std::runtime_error("Game Catalog requires games[].products array");
        }
        Statement products(parser.handle(), R"sql(
            SELECT json_extract(value, '$.store'), json_type(value, '$.store'),
                   json_extract(value, '$.productId'), json_type(value, '$.productId'),
                   json_extract(value, '$.productUrl'), json_type(value, '$.productUrl'),
                   json_extract(value, '$.platforms'), json_type(value, '$.platforms'),
                   json_extract(value, '$.region'), json_type(value, '$.region'),
                   json_extract(value, '$.edition'), json_type(value, '$.edition'),
                   json_extract(value, '$.offerType'), json_type(value, '$.offerType'),
                   json_extract(value, '$.compatibility'),
                   json_type(value, '$.compatibility')
            FROM json_each(?1);
        )sql");
        products.bindJson(*productsJson);
        bool foundProduct = false;
        while (products.next()) {
            const auto storeName = products.optionalText(0);
            const auto productId = products.optionalText(2);
            const auto productUrl = products.optionalText(4);
            const auto regionName = products.optionalText(8);
            const auto editionName = products.optionalText(10);
            const auto offerTypeName = products.optionalText(12);
            requireJsonString(storeName, products.optionalText(1), "products[].store");
            requireJsonString(productId, products.optionalText(3), "products[].productId");
            requireJsonString(productUrl, products.optionalText(5), "products[].productUrl");
            requireJsonString(regionName, products.optionalText(9), "products[].region");
            requireJsonString(editionName, products.optionalText(11), "products[].edition");
            requireJsonString(offerTypeName, products.optionalText(13), "products[].offerType");
            if (productUrl->rfind("https://", 0) != 0) {
                throw std::runtime_error("Game Catalog productUrl must use HTTPS");
            }
            const auto store = storeFromString(*storeName);
            const auto region = regionFromString(*regionName);
            const auto edition = editionFromString(*editionName);
            const auto offerType = offerTypeFromString(*offerTypeName);
            auto productPlatforms = parsePlatforms(
                parser.handle(), products.optionalText(6), products.optionalText(7));
            auto compatibility = parseCompatibility(
                parser.handle(), products.optionalText(14), products.optionalText(15));
            for (const auto platform : productPlatforms) {
                if (std::find(games_.back().supportedPlatforms.begin(),
                              games_.back().supportedPlatforms.end(), platform) ==
                    games_.back().supportedPlatforms.end()) {
                    throw std::runtime_error(
                        "Store product platform is not supported by its Game");
                }
            }
            for (const auto& entry : compatibility) {
                if (std::find(games_.back().supportedPlatforms.begin(),
                              games_.back().supportedPlatforms.end(), entry.platform) ==
                    games_.back().supportedPlatforms.end()) {
                    throw std::runtime_error(
                        "Compatibility platform is not supported by its Game");
                }
            }
            if (std::any_of(
                    storeProducts_.begin(), storeProducts_.end(),
                    [&](const CatalogStoreProduct& product) {
                        return product.store == store && product.productId == *productId;
                    })) {
                throw std::runtime_error(
                    "Duplicate Store product id in Game Catalog: " + *productId);
            }
            storeProducts_.push_back(CatalogStoreProduct{
                *id, store, *productId, *productUrl, std::move(productPlatforms),
                region, edition, offerType, std::move(compatibility)});
            foundProduct = true;
        }
        if (!foundProduct) {
            throw std::runtime_error("Game Catalog game has no Store products: " + *id);
        }
    }
    if (games_.empty()) throw std::runtime_error("Game Catalog games array cannot be empty");
}

void GameCatalog::reload(const std::string& dataPath) {
    GameCatalog refreshed(dataPath);
    std::unique_lock<std::shared_mutex> lock(mutex_);
    games_.swap(refreshed.games_);
    storeProducts_.swap(refreshed.storeProducts_);
}

std::optional<Game> GameCatalog::findByName(const std::string& name) const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    const auto normalized = normalizeName(name);
    const auto found = std::find_if(games_.begin(), games_.end(), [&](const Game& game) {
        return game.normalizedTitle == normalized ||
            std::find(
                game.normalizedAliases.begin(),
                game.normalizedAliases.end(),
                normalized) != game.normalizedAliases.end();
    });
    return found == games_.end() ? std::nullopt : std::optional<Game>{*found};
}

std::optional<Game> GameCatalog::findById(const std::string& id) const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    const auto found = std::find_if(games_.begin(), games_.end(), [&](const Game& game) {
        return game.id == id;
    });
    return found == games_.end() ? std::nullopt : std::optional<Game>{*found};
}

std::vector<Game> GameCatalog::searchByName(const std::string& query) const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    const auto normalized = normalizeName(query);
    if (normalized.empty()) return {};

    std::vector<Game> matches;
    for (const auto& game : games_) {
        const auto aliasMatches = std::any_of(
            game.normalizedAliases.begin(),
            game.normalizedAliases.end(),
            [&](const auto& alias) {
                return alias.find(normalized) != std::string::npos;
            });
        if (game.normalizedTitle.find(normalized) != std::string::npos ||
            aliasMatches) {
            matches.push_back(game);
        }
    }
    return matches;
}

std::vector<Game> GameCatalog::filterGames(
    const GameCatalogFilter& filter) const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    const auto normalizedQuery = normalizeName(filter.query);
    const auto normalizedGenre = normalizeName(filter.genre);
    const auto normalizedTag = normalizeName(filter.tag);
    std::vector<Game> result;
    for (const auto& game : games_) {
        const auto aliasMatches = std::any_of(
            game.normalizedAliases.begin(),
            game.normalizedAliases.end(),
            [&](const auto& alias) {
                return alias.find(normalizedQuery) != std::string::npos;
            });
        if (!normalizedQuery.empty() &&
            game.normalizedTitle.find(normalizedQuery) == std::string::npos &&
            !aliasMatches) {
            continue;
        }
        if (filter.platform &&
            std::find(
                game.supportedPlatforms.begin(),
                game.supportedPlatforms.end(),
                *filter.platform) == game.supportedPlatforms.end()) {
            continue;
        }
        if (!normalizedGenre.empty() &&
            std::none_of(game.genres.begin(), game.genres.end(), [&](const auto& genre) {
                return normalizeName(genre) == normalizedGenre;
            })) {
            continue;
        }
        if (!normalizedTag.empty() &&
            std::none_of(game.tags.begin(), game.tags.end(), [&](const auto& tag) {
                return normalizeName(tag) == normalizedTag;
            })) {
            continue;
        }
        if (filter.store &&
            std::none_of(
                storeProducts_.begin(),
                storeProducts_.end(),
                [&](const auto& product) {
                    return product.gameId == game.id && product.store == *filter.store;
                })) {
            continue;
        }
        result.push_back(game);
    }
    return result;
}

std::vector<Game> GameCatalog::allGames() const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    return games_;
}

std::vector<CatalogStoreProduct> GameCatalog::storeProducts(Store store) const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    std::vector<CatalogStoreProduct> result;
    std::copy_if(
        storeProducts_.begin(), storeProducts_.end(), std::back_inserter(result),
        [store](const CatalogStoreProduct& product) { return product.store == store; });
    return result;
}

std::optional<CatalogStoreProduct> GameCatalog::findStoreProduct(
    Store store,
    const std::string& productId) const {
    std::shared_lock<std::shared_mutex> lock(mutex_);
    const auto found = std::find_if(
        storeProducts_.begin(), storeProducts_.end(),
        [store, &productId](const CatalogStoreProduct& product) {
            return product.store == store && product.productId == productId;
        });
    return found == storeProducts_.end()
        ? std::nullopt
        : std::optional<CatalogStoreProduct>{*found};
}

}  // namespace game_price
