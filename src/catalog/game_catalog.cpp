#include "game_price/catalog/game_catalog.h"

#include "game_price/persistence/database.h"
#include "game_price/support/text_utils.h"

#include <sqlite3.h>

#include <algorithm>
#include <fstream>
#include <iterator>
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
    throw std::runtime_error("Unsupported Game Catalog platform: " + value);
}

Store storeFromString(const std::string& value) {
    if (value == "Steam") return Store::Steam;
    if (value == "EpicGamesStore") return Store::EpicGamesStore;
    if (value == "GooglePlay") return Store::GooglePlay;
    if (value == "AppleAppStore") return Store::AppleAppStore;
    throw std::runtime_error("Unsupported Game Catalog Store: " + value);
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
    if (!header.next() || header.integer(0) != 1 || header.integer(1) != 2 ||
        header.optionalText(2) != std::optional<std::string>{"integer"} ||
        header.optionalText(3) != std::optional<std::string>{"array"}) {
        throw std::runtime_error(
            "Game Catalog must be valid JSON with schemaVersion 2 and games array");
    }

    Statement rows(parser.handle(), R"sql(
        SELECT json_extract(value, '$.id'), json_type(value, '$.id'),
               json_extract(value, '$.title'), json_type(value, '$.title'),
               json_extract(value, '$.platforms'), json_type(value, '$.platforms'),
               json_extract(value, '$.products'), json_type(value, '$.products')
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
        if (std::any_of(games_.begin(), games_.end(), [&](const Game& game) {
                return game.id == *id || game.normalizedTitle == normalizedTitle;
            })) {
            throw std::runtime_error("Duplicate Game Catalog id or title: " + *id);
        }
        auto platforms = parsePlatforms(
            parser.handle(), rows.optionalText(4), rows.optionalText(5));
        games_.push_back(Game{*id, *title, normalizedTitle, std::move(platforms)});

        const auto productsJson = rows.optionalText(6);
        if (!productsJson || rows.optionalText(7) != std::optional<std::string>{"array"}) {
            throw std::runtime_error("Game Catalog requires games[].products array");
        }
        Statement products(parser.handle(), R"sql(
            SELECT json_extract(value, '$.store'), json_type(value, '$.store'),
                   json_extract(value, '$.productId'), json_type(value, '$.productId'),
                   json_extract(value, '$.productUrl'), json_type(value, '$.productUrl'),
                   json_extract(value, '$.platforms'), json_type(value, '$.platforms')
            FROM json_each(?1);
        )sql");
        products.bindJson(*productsJson);
        bool foundProduct = false;
        while (products.next()) {
            const auto storeName = products.optionalText(0);
            const auto productId = products.optionalText(2);
            const auto productUrl = products.optionalText(4);
            requireJsonString(storeName, products.optionalText(1), "products[].store");
            requireJsonString(productId, products.optionalText(3), "products[].productId");
            requireJsonString(productUrl, products.optionalText(5), "products[].productUrl");
            if (productUrl->rfind("https://", 0) != 0) {
                throw std::runtime_error("Game Catalog productUrl must use HTTPS");
            }
            const auto store = storeFromString(*storeName);
            auto productPlatforms = parsePlatforms(
                parser.handle(), products.optionalText(6), products.optionalText(7));
            for (const auto platform : productPlatforms) {
                if (std::find(games_.back().supportedPlatforms.begin(),
                              games_.back().supportedPlatforms.end(), platform) ==
                    games_.back().supportedPlatforms.end()) {
                    throw std::runtime_error(
                        "Store product platform is not supported by its Game");
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
                *id, store, *productId, *productUrl, std::move(productPlatforms)});
            foundProduct = true;
        }
        if (!foundProduct) {
            throw std::runtime_error("Game Catalog game has no Store products: " + *id);
        }
    }
    if (games_.empty()) throw std::runtime_error("Game Catalog games array cannot be empty");
}

std::optional<Game> GameCatalog::findByName(const std::string& name) const {
    const auto normalized = normalizeName(name);
    const auto found = std::find_if(games_.begin(), games_.end(), [&](const Game& game) {
        return game.normalizedTitle == normalized;
    });
    return found == games_.end() ? std::nullopt : std::optional<Game>{*found};
}

std::optional<Game> GameCatalog::findById(const std::string& id) const {
    const auto found = std::find_if(games_.begin(), games_.end(), [&](const Game& game) {
        return game.id == id;
    });
    return found == games_.end() ? std::nullopt : std::optional<Game>{*found};
}

std::vector<Game> GameCatalog::searchByName(const std::string& query) const {
    const auto normalized = normalizeName(query);
    if (normalized.empty()) return {};

    std::vector<Game> matches;
    for (const auto& game : games_) {
        if (game.normalizedTitle.find(normalized) != std::string::npos) {
            matches.push_back(game);
        }
    }
    return matches;
}

const std::vector<Game>& GameCatalog::allGames() const noexcept {
    return games_;
}

std::vector<CatalogStoreProduct> GameCatalog::storeProducts(Store store) const {
    std::vector<CatalogStoreProduct> result;
    std::copy_if(
        storeProducts_.begin(), storeProducts_.end(), std::back_inserter(result),
        [store](const CatalogStoreProduct& product) { return product.store == store; });
    return result;
}

}  // namespace game_price
