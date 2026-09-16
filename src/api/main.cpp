#include "game_price/app/game_query_service.h"
#include "game_price/domain/domain_types.h"
#include "game_price/persistence/database.h"
#include "game_price/persistence/store_product_repository.h"
#include "game_price/notification/account_repository.h"
#include "game_price/notification/auth_service.h"
#include "game_price/notification/oauth_service.h"
#include "game_price/support/date_utils.h"
#include <drogon/utils/Utilities.h>

#include <drogon/drogon.h>
#include <sqlite3.h>

#include <cstdlib>
#include <algorithm>
#include <cctype>
#include <chrono>
#include <cmath>
#include <iostream>
#include <filesystem>
#include <fstream>
#include <regex>
#include <set>
#include <sstream>
#include <iterator>
#include <mutex>
#include <optional>
#include <thread>
#include <stdexcept>
#include <string>
#include <map>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {

using namespace game_price;
using drogon::HttpResponse;
using drogon::HttpResponsePtr;

struct CatalogGameSummary {
    Game game;
    std::optional<Money> lowestPrice;
    std::optional<int> maxDiscountPercent;
    std::string lastUpdatedAt;
    std::string priceStatus;
};

bool supportedGameSort(const std::string& sort) {
    static const std::set<std::string> supported{
        "title",
        "titleAsc",
        "titleDesc",
        "lowestPrice",
        "recentlyUpdated",
        "updatedDesc",
        "updatedAsc",
        "discountDesc",
        "discountAsc",
    };
    return sort.empty() || supported.count(sort) > 0;
}

bool catalogSummaryLess(
    const CatalogGameSummary& left,
    const CatalogGameSummary& right,
    const std::string& sort) {
    if (sort == "titleDesc") {
        return left.game.title > right.game.title;
    }
    if (sort == "lowestPrice") {
        if (left.lowestPrice && right.lowestPrice) {
            if (left.lowestPrice->currency != right.lowestPrice->currency) {
                if (left.lowestPrice->currency == Currency::KRW) return true;
                if (right.lowestPrice->currency == Currency::KRW) return false;
                return toString(left.lowestPrice->currency) <
                    toString(right.lowestPrice->currency);
            }
            if (left.lowestPrice->minorAmount !=
                right.lowestPrice->minorAmount) {
                return left.lowestPrice->minorAmount <
                    right.lowestPrice->minorAmount;
            }
        }
        if (left.lowestPrice.has_value() != right.lowestPrice.has_value()) {
            return left.lowestPrice.has_value();
        }
    }
    if (sort == "discountDesc" || sort == "discountAsc") {
        if (left.maxDiscountPercent && right.maxDiscountPercent &&
            *left.maxDiscountPercent != *right.maxDiscountPercent) {
            if (sort == "discountDesc") {
                return *left.maxDiscountPercent > *right.maxDiscountPercent;
            }
            return *left.maxDiscountPercent < *right.maxDiscountPercent;
        }
        if (left.maxDiscountPercent.has_value() != right.maxDiscountPercent.has_value()) {
            return left.maxDiscountPercent.has_value();
        }
    }
    if (sort == "updatedDesc" || sort == "recentlyUpdated" || sort == "updatedAsc") {
        if (left.lastUpdatedAt.empty() != right.lastUpdatedAt.empty()) {
            return !left.lastUpdatedAt.empty();
        }
        if (left.lastUpdatedAt != right.lastUpdatedAt) {
            if (sort == "updatedAsc") {
                return left.lastUpdatedAt < right.lastUpdatedAt;
            }
            return left.lastUpdatedAt > right.lastUpdatedAt;
        }
    }
    return left.game.title < right.game.title;
}

std::size_t unsignedParameter(
    const std::string& value,
    std::size_t defaultValue,
    std::size_t maximum,
    const std::string& name) {
    if (value.empty()) {
        return defaultValue;
    }
    if (!std::all_of(value.begin(), value.end(), [](unsigned char character) {
            return std::isdigit(character) != 0;
        })) {
        throw std::invalid_argument(name + " must be a positive integer");
    }
    const auto parsed = std::stoull(value);
    if (parsed == 0 || parsed > maximum) {
        throw std::invalid_argument(name + " is outside the supported range");
    }
    return static_cast<std::size_t>(parsed);
}

Json::Value moneyJson(const Money& money) {
    Json::Value json;
    json["minorAmount"] = Json::Int64(money.minorAmount);
    json["currency"] = toString(money.currency);
    return json;
}

Json::Value gameJson(const Game& game) {
    Json::Value json;
    json["id"] = game.id;
    json["title"] = game.title;
    if (!game.imageUrl.empty()) {
        json["imageUrl"] = game.imageUrl;
    }
    json["platforms"] = Json::arrayValue;
    for (const auto platform : game.supportedPlatforms) {
        json["platforms"].append(toString(platform));
    }
    json["genres"] = Json::arrayValue;
    for (const auto& genre : game.genres) {
        json["genres"].append(genre);
    }
    json["tags"] = Json::arrayValue;
    for (const auto& tag : game.tags) {
        json["tags"].append(tag);
    }
    json["aliases"] = Json::arrayValue;
    for (const auto& alias : game.aliases) {
        json["aliases"].append(alias);
    }
    json["developers"] = Json::arrayValue;
    for (const auto& developer : game.developers) {
        json["developers"].append(developer);
    }
    json["publishers"] = Json::arrayValue;
    for (const auto& publisher : game.publishers) {
        json["publishers"].append(publisher);
    }
    return json;
}

std::optional<Json::Value> convertedKrwJson(
    Database& database,
    const Money& money,
    const std::string& observedAt) {
    if (money.currency == Currency::KRW) return std::nullopt;
    sqlite3_stmt* statement = nullptr;
    const char* sql = R"sql(
        SELECT rate_date, rate, source
        FROM exchange_rates
        WHERE base_currency = ? AND quote_currency = 'KRW'
          AND rate_date <= ?
        ORDER BY rate_date DESC
        LIMIT 1
    )sql";
    if (sqlite3_prepare_v2(database.handle(), sql, -1, &statement, nullptr) !=
        SQLITE_OK) {
        return std::nullopt;
    }
    const auto currency = toString(money.currency);
    const auto date = observedAt.substr(0, std::min<std::size_t>(10, observedAt.size()));
    sqlite3_bind_text(
        statement, 1, currency.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(statement, 2, date.c_str(), -1, SQLITE_TRANSIENT);
    std::optional<Json::Value> result;
    if (sqlite3_step(statement) == SQLITE_ROW) {
        const auto rateDate = reinterpret_cast<const char*>(
            sqlite3_column_text(statement, 0));
        const double rate = sqlite3_column_double(statement, 1);
        const auto source = reinterpret_cast<const char*>(
            sqlite3_column_text(statement, 2));
        const double unitAmount = money.currency == Currency::JPY
            ? static_cast<double>(money.minorAmount)
            : static_cast<double>(money.minorAmount) / 100.0;
        Json::Value json;
        json["price"]["minorAmount"] = Json::Int64(
            std::llround(unitAmount * rate));
        json["price"]["currency"] = "KRW";
        json["rate"] = rate;
        json["rateDate"] = rateDate;
        json["source"] = source;
        result = std::move(json);
    }
    sqlite3_finalize(statement);
    return result;
}

Json::Value productJson(
    const ProductPriceReport& report,
    Database* database = nullptr,
    const std::optional<Money>& effectiveAllocatedPrice = std::nullopt) {
    Json::Value json;
    json["productId"] = report.product.productId;
    json["store"] = toString(report.product.store);
    json["purchaseUrl"] = report.purchaseUrl;
    json["region"] = toString(report.product.region);
    json["edition"] = toString(report.product.edition);
    json["offerType"] = toString(report.product.offerType);
    if (!report.offerName.empty()) json["offerName"] = report.offerName;
    json["price"] = moneyJson(report.product.currentPrice);
    if (report.product.regularPrice) {
        json["regularPrice"] = moneyJson(*report.product.regularPrice);
    }
    json["discountPercent"] = report.product.discountPercent;
    if (effectiveAllocatedPrice) {
        json["effectiveAllocatedPrice"] = moneyJson(*effectiveAllocatedPrice);
        json["effectivePriceMethod"] = "ProportionalToStandaloneRegularPrice";
    }
    json["purchasable"] = report.product.purchasable;
    if (report.product.lastCheckedAt) {
        json["lastCheckedAt"] = *report.product.lastCheckedAt;
    }
    if (report.product.lastSuccessfulCheckAt) {
        json["lastSuccessfulCheckAt"] =
            *report.product.lastSuccessfulCheckAt;
        if (database != nullptr) {
            if (const auto converted = convertedKrwJson(
                    *database,
                    report.product.currentPrice,
                    *report.product.lastSuccessfulCheckAt)) {
                json["krwConversion"] = *converted;
            }
        }
    }
    json["freshness"] = toString(report.product.freshness);
    json["stale"] = report.product.freshness != PriceFreshness::Fresh;
    for (const auto platform : report.product.supportedPlatforms) {
        json["platforms"].append(toString(platform));
    }
    json["compatibility"] = Json::arrayValue;
    for (const auto& entry : report.product.compatibility) {
        Json::Value compatibility;
        compatibility["platform"] = toString(entry.platform);
        compatibility["status"] = toString(entry.status);
        json["compatibility"].append(std::move(compatibility));
    }
    if (report.history) {
        Json::Value history;
        history["lowestPrice"] = moneyJson(report.history->lowestPrice);
        history["highestPrice"] = moneyJson(report.history->highestPrice);
        history["averagePrice"] = moneyJson(report.history->averagePrice);
        history["trend"] = toString(report.history->trend);
        history["observationCount"] =
            Json::UInt64(report.history->observationCount);
        json["history"] = std::move(history);
    }
    if (report.recommendation) {
        Json::Value recommendation;
        recommendation["rating"] = toString(report.recommendation->recommendation);
        recommendation["amountAboveHistoricalLow"] =
            Json::Int64(report.recommendation->amountAboveHistoricalLow);
        recommendation["percentAboveHistoricalLow"] =
            report.recommendation->percentAboveHistoricalLow;
        recommendation["percentComparedToAverage"] =
            report.recommendation->percentComparedToAverage;
        if (report.recommendation->priceRangePositionPercent) {
            recommendation["priceRangePositionPercent"] =
                *report.recommendation->priceRangePositionPercent;
        }
        for (const auto& reason : report.recommendation->reasons) {
            recommendation["reasons"].append(reason);
        }
        json["recommendation"] = std::move(recommendation);
    }
    return json;
}

HttpResponsePtr jsonResponse(
    const Json::Value& json,
    drogon::HttpStatusCode status = drogon::k200OK) {
    auto response = HttpResponse::newHttpJsonResponse(json);
    response->setStatusCode(status);
    const char* webOrigin=std::getenv("WEB_APP_URL");
    response->addHeader("Access-Control-Allow-Origin", webOrigin?webOrigin:"http://127.0.0.1:5173");
    response->addHeader("Access-Control-Allow-Credentials", "true");
    response->addHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
    response->addHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, PATCH, OPTIONS");
    return response;
}

HttpResponsePtr jsonError(drogon::HttpStatusCode status, const std::string& message) {
    Json::Value json;
    json["error"] = message;
    return jsonResponse(json, status);
}

std::string env(const char* name) {
    const char* value = std::getenv(name);
    return value ? value : "";
}

int serverPort() {
    const char* value = std::getenv("GAME_PRICE_API_PORT");
    return value ? std::stoi(value) : 8080;
}

std::string serverHost() {
    const auto value = env("GAME_PRICE_API_HOST");
    if (value.empty()) {
        return "127.0.0.1";
    }
    return value;
}

std::string databasePath() {
    const char* value = std::getenv("GAME_PRICE_DATABASE_PATH");
    return value ? value : GAME_PRICE_DATABASE_PATH;
}

std::string catalogPath() {
    const char* value = std::getenv("GAME_PRICE_CATALOG_PATH");
    return value
        ? value
        : std::string(SAMPLE_DATA_DIR) + "/game_catalog.json";
}

std::filesystem::path projectPath() {
    const auto value = env("GAME_PRICE_PROJECT_PATH");
    return value.empty()
        ? std::filesystem::path(PROJECT_SOURCE_DIR)
        : std::filesystem::path(value);
}

std::filesystem::path trackerPath() {
    const auto value = env("GAME_PRICE_TRACKER_PATH");
    return value.empty()
        ? projectPath() / "build/game_price_tracker"
        : std::filesystem::path(value);
}

std::filesystem::path collectionLockPath() {
    const auto value = env("COLLECTION_LOCK_PATH");
    return value.empty()
        ? std::filesystem::path("/tmp/dealquest-collection.lock")
        : std::filesystem::path(value);
}

int acquireCollectionLock() {
    const auto path = collectionLockPath();
    const auto descriptor = ::open(
        path.c_str(),
        O_CREAT | O_WRONLY | O_CLOEXEC,
        0644);
    if (descriptor < 0) {
        return -1;
    }
    if (::flock(descriptor, LOCK_EX | LOCK_NB) == 0) {
        return descriptor;
    }
    ::close(descriptor);
    return -1;
}

void releaseCollectionLock(int descriptor) {
    if (descriptor < 0) {
        return;
    }
    ::flock(descriptor, LOCK_UN);
    ::close(descriptor);
}

bool catalogAdminEnabled() {
    const char* value = std::getenv("CATALOG_ADMIN_ENABLED");
    return value && std::string(value) == "true";
}

void validateRuntimeConfiguration() {
    if (env("APP_ENV") != "production") {
        return;
    }
    const auto webUrl = env("WEB_APP_URL");
    const auto callbackBase = env("OAUTH_CALLBACK_BASE");
    if (webUrl.rfind("https://", 0) != 0) {
        throw std::runtime_error(
            "production WEB_APP_URL must use HTTPS");
    }
    if (callbackBase.rfind("https://", 0) != 0) {
        throw std::runtime_error(
            "production OAUTH_CALLBACK_BASE must use HTTPS");
    }
    if (env("COOKIE_SECURE") != "true") {
        throw std::runtime_error(
            "production COOKIE_SECURE must be true");
    }
    const auto validateCredentialPair = [](const char* idName,
                                            const char* secretName) {
        const auto clientId = env(idName);
        const auto clientSecret = env(secretName);
        if (clientId.empty() != clientSecret.empty()) {
            throw std::runtime_error(
                std::string(idName) + " and " + secretName +
                " must be configured together");
        }
    };
    validateCredentialPair(
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET");
    validateCredentialPair(
        "NAVER_OAUTH_CLIENT_ID",
        "NAVER_OAUTH_CLIENT_SECRET");
}

bool validSteamAppId(const std::string& value) {
    return !value.empty() &&
        std::all_of(value.begin(), value.end(), [](unsigned char character) {
            return std::isdigit(character) != 0;
        });
}

bool validCanonicalGameId(const std::string& value) {
    static const std::regex pattern{"[a-z0-9]+(?:-[a-z0-9]+)*"};
    const auto containsLetter = std::any_of(
        value.begin(),
        value.end(),
        [](unsigned char character) {
            return std::islower(character) != 0;
        });
    return value.empty() ||
        (containsLetter && std::regex_match(value, pattern));
}

bool validGooglePlayPackage(const std::string& value) {
    static const std::regex pattern{
        "[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)+"};
    return std::regex_match(value, pattern);
}

bool validAppleTrackId(const std::string& value) {
    return !value.empty() &&
        std::all_of(value.begin(), value.end(), [](unsigned char character) {
            return std::isdigit(character) != 0;
        });
}

std::string shellQuoted(const std::string& value) {
    std::string result{"'"};
    for (const auto character : value) {
        if (character == '\'') {
            result += "'\\''";
        } else {
            result += character;
        }
    }
    result += '\'';
    return result;
}

std::mutex& catalogToolMutex() {
    static std::mutex mutex;
    return mutex;
}

std::string catalogImportError(const std::string& output) {
    const auto marker = output.rfind("error: ");
    if (marker == std::string::npos) {
        return output.empty() ? "catalog import failed" : output;
    }
    auto message = output.substr(marker + 7);
    while (!message.empty() &&
           (message.back() == '\n' || message.back() == '\r')) {
        message.pop_back();
    }
    return message;
}

Json::Value executeCatalogTool(
    std::string command,
    const std::filesystem::path& temporary,
    bool acceptFailureReport = false) {
    command += " > " + shellQuoted(temporary.string());
    command += " 2>&1";
    const auto exitCode = std::system(command.c_str());
    std::ifstream input(temporary);
    const std::string output{
        std::istreambuf_iterator<char>{input},
        std::istreambuf_iterator<char>{}};
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    if (exitCode != 0 && !acceptFailureReport) {
        const auto message = catalogImportError(output);
        if (message == "Steam title cannot produce a canonical game id") {
            throw std::invalid_argument(
                "canonical game ID is required for this title");
        }
        throw std::invalid_argument(message);
    }
    const auto jsonEnd = output.rfind("}\n");
    if (jsonEnd == std::string::npos) {
        throw std::runtime_error("catalog importer returned invalid output");
    }
    Json::Value result;
    Json::CharReaderBuilder builder;
    std::string errors;
    std::istringstream jsonInput(output.substr(0, jsonEnd + 1));
    if (!Json::parseFromStream(builder, jsonInput, &result, &errors)) {
        throw std::runtime_error("catalog importer returned invalid JSON");
    }
    return result;
}

Json::Value runCatalogImport(
    const std::string& appId,
    const std::string& gameId,
    bool apply) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        ("compgameprice-catalog-" + appId + ".json");
    const auto script = projectPath() /
        "tools/add_steam_catalog_game.py";
    const auto catalog = std::filesystem::path(catalogPath());
    std::string command = "python3 " + shellQuoted(script.string()) +
        " --app-id " + appId +
        " --catalog " + shellQuoted(catalog.string());
    command += " --database " + shellQuoted(databasePath());
    if (!gameId.empty()) {
        command += " --game-id " + gameId;
    }
    if (apply) {
        command += " --apply";
    }
    return executeCatalogTool(std::move(command), temporary);
}

Json::Value runGooglePlayCatalogImport(
    const std::string& packageName,
    const std::string& gameId,
    bool apply,
    bool acknowledgeReview) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-google-play-catalog.json";
    const auto script = projectPath() /
        "tools/add_google_play_catalog_game.py";
    const auto catalog = std::filesystem::path(catalogPath());
    std::string command = "python3 " + shellQuoted(script.string()) +
        " --package-name " + shellQuoted(packageName) +
        " --game-id " + shellQuoted(gameId) +
        " --catalog " + shellQuoted(catalog.string());
    command += " --database " + shellQuoted(databasePath());
    if (apply) {
        command += " --apply";
    }
    if (acknowledgeReview) {
        command += " --acknowledge-review";
    }
    return executeCatalogTool(std::move(command), temporary);
}

Json::Value runAppleCatalogImport(
    const std::string& trackId,
    const std::string& gameId,
    bool apply,
    bool acknowledgeReview) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-apple-catalog.json";
    const auto script = projectPath() /
        "tools/add_apple_catalog_game.py";
    const auto catalog = std::filesystem::path(catalogPath());
    std::string command = "python3 " + shellQuoted(script.string()) +
        " --track-id " + shellQuoted(trackId) +
        " --game-id " + shellQuoted(gameId) +
        " --catalog " + shellQuoted(catalog.string());
    command += " --database " + shellQuoted(databasePath());
    if (apply) {
        command += " --apply";
    }
    if (acknowledgeReview) {
        command += " --acknowledge-review";
    }
    return executeCatalogTool(std::move(command), temporary);
}

Json::Value runStorefrontCatalogImport(
    const std::string& store,
    const std::string& productUrl,
    const std::string& gameId,
    bool apply,
    bool acknowledgeReview) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-storefront-catalog.json";
    const auto script = projectPath() /
        "tools/add_storefront_catalog_game.py";
    const auto catalog = std::filesystem::path(catalogPath());
    std::string command = "python3 " + shellQuoted(script.string());
    command += " --store " + shellQuoted(store);
    command += " --product-url " + shellQuoted(productUrl);
    command += " --game-id " + shellQuoted(gameId);
    command += " --catalog " + shellQuoted(catalog.string());
    command += " --database " + shellQuoted(databasePath());
    if (apply) {
        command += " --apply";
    }
    if (acknowledgeReview) {
        command += " --acknowledge-review";
    }
    return executeCatalogTool(std::move(command), temporary);
}

Json::Value runCatalogMetadataUpdate(
    const std::string& gameId,
    const Json::Value& metadata,
    bool apply) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporaryDirectory = std::filesystem::temp_directory_path();
    const auto input = temporaryDirectory /
        "compgameprice-catalog-metadata-input.json";
    const auto output = temporaryDirectory /
        "compgameprice-catalog-metadata-output.json";
    {
        std::ofstream stream(input);
        Json::StreamWriterBuilder builder;
        builder["indentation"] = "  ";
        stream << Json::writeString(builder, metadata);
    }
    const auto script = projectPath() /
        "tools/update_catalog_game_metadata.py";
    const auto catalog = std::filesystem::path(catalogPath());
    std::string command = "python3 " + shellQuoted(script.string());
    command += " --game-id " + shellQuoted(gameId);
    command += " --catalog " + shellQuoted(catalog.string());
    command += " --input " + shellQuoted(input.string());
    command += " --database " + shellQuoted(databasePath());
    if (apply) {
        command += " --apply";
    }
    try {
        auto result = executeCatalogTool(std::move(command), output);
        std::error_code ignored;
        std::filesystem::remove(input, ignored);
        return result;
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(input, ignored);
        throw;
    }
}

Json::Value runCatalogAuditList(int limit) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-catalog-audits.json";
    const auto script = projectPath() /
        "tools/list_catalog_audits.py";
    std::string command = "python3 " + shellQuoted(script.string());
    command += " --database " + shellQuoted(databasePath());
    command += " --limit " + std::to_string(limit);
    return executeCatalogTool(std::move(command), temporary);
}

Json::Value runStoreSearch(const std::string& store, const std::string& query) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    if (store != "Steam" && store != "Google Play" &&
        store != "Apple App Store" && store != "Nintendo eShop" &&
        store != "Ubisoft Store" && store != "GOG") {
        throw std::invalid_argument("store is not supported yet");
    }
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-store-search.json";
    std::string scriptName;
    if (store == "Steam") {
        scriptName = "tools/search_steam_catalog.py";
    } else if (store == "Google Play") {
        scriptName = "tools/search_google_play_catalog.py";
    } else if (store == "Apple App Store") {
        scriptName = "tools/search_apple_catalog.py";
    } else if (store == "Nintendo eShop") {
        scriptName = "tools/search_nintendo_catalog.py";
    } else {
        scriptName = "tools/search_storefront_catalog.py";
    }
    const auto script = projectPath() / scriptName;
    auto command = "python3 " + shellQuoted(script.string());
    if (store == "Ubisoft Store") command += " --store UbisoftStore";
    if (store == "GOG") command += " --store GOG";
    command +=
        " --query " + shellQuoted(query) +
        " > " + shellQuoted(temporary.string()) + " 2>&1";
    const auto exitCode = std::system(command.c_str());
    std::ifstream input(temporary);
    Json::Value result;
    Json::CharReaderBuilder builder;
    std::string errors;
    const auto parsed = Json::parseFromStream(builder, input, &result, &errors);
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    if (exitCode != 0 || !parsed) {
        throw std::runtime_error("Store search failed");
    }
    return result;
}

Json::Value runPriceIntegrityAudit() {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-price-integrity.json";
    const auto script = projectPath() /
        "tools/audit_catalog_price_integrity.py";
    std::string command = "python3 " + shellQuoted(script.string());
    command += " --catalog " + shellQuoted(catalogPath());
    command += " --database " + shellQuoted(databasePath());
    return executeCatalogTool(std::move(command), temporary);
}

class CatalogCollectionJob {
public:
    bool start(
        const std::string& store,
        const std::optional<std::string>& productId = std::nullopt) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (status_ == "RUNNING") {
            return false;
        }
        const auto lockDescriptor = acquireCollectionLock();
        if (lockDescriptor < 0) {
            return false;
        }
        ++id_;
        if (!progressPath_.empty()) {
            std::error_code ignored;
            std::filesystem::remove(progressPath_, ignored);
        }
        progressPath_ = (std::filesystem::temp_directory_path() /
            ("compgameprice-collection-" + std::to_string(getpid()) + "-" + std::to_string(id_) + ".json")).string();
        phase_ = "PREPARING";
        store_ = store;
        productId_ = productId.value_or("");
        status_ = "RUNNING";
        error_.clear();
        integrityIssueCount_ = 0;
        const auto selectedStore = store_;
        const auto selectedProductId = productId_;
        std::thread([this, selectedStore, selectedProductId, lockDescriptor]() {
            run(selectedStore, selectedProductId, lockDescriptor);
        }).detach();
        return true;
    }

    Json::Value json() const {
        std::lock_guard<std::mutex> lock(mutex_);
        Json::Value result;
        result["id"] = Json::UInt64(id_);
        result["status"] = status_;
        result["store"] = store_;
        if (!productId_.empty()) {
            result["productId"] = productId_;
        }
        if (!error_.empty()) {
            result["error"] = error_;
        }
        result["integrityIssueCount"] = Json::UInt64(integrityIssueCount_);
        result["phase"] = phase_;
        std::ifstream progressInput(progressPath_);
        Json::Value progress;
        Json::CharReaderBuilder builder;
        std::string errors;
        if (progressInput && Json::parseFromStream(builder, progressInput, &progress, &errors)) {
            result["progress"] = progress;
            if (status_ == "RUNNING" && phase_ != "AUDITING") {
                result["phase"] = progress["processed"].asUInt64() < progress["total"].asUInt64()
                    ? "COLLECTING" : "SAVING";
            }
        }
        return result;
    }

private:
    void run(
        const std::string& store,
        const std::string& productId,
        int lockDescriptor) {
        const auto project = projectPath();
        std::string pipeline;
        std::string pipelineArguments;
        if (store == "Google Play") {
            pipeline = "tools/run_google_play_pipeline.py";
        } else if (store == "Apple App Store") {
            pipeline = "tools/run_apple_pipeline.py";
        } else if (store == "Epic Games Store") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store EpicGamesStore";
        } else if (store == "Nintendo eShop") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store NintendoEShop";
        } else if (store == "PlayStation Store") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store PlayStationStore";
        } else if (store == "Microsoft Store") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store MicrosoftStore";
        } else if (store == "Ubisoft Store") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store UbisoftStore";
        } else if (store == "GOG") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store GOG";
        } else if (store == "Meta Quest Store") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store MetaQuestStore";
        } else if (store == "EA app") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store EAApp";
        } else if (store == "Battle.net") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store BattleNet";
        } else if (store == "itch.io") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store ItchIo";
        } else if (store == "Humble Store") {
            pipeline = "tools/run_storefront_price_pipeline.py";
            pipelineArguments = " --store HumbleStore";
        } else {
            pipeline = "tools/run_steam_pipeline.py";
        }
        if (!productId.empty() &&
            (pipeline == "tools/run_storefront_price_pipeline.py" ||
             pipeline == "tools/run_steam_pipeline.py" ||
             pipeline == "tools/run_google_play_pipeline.py" ||
             pipeline == "tools/run_apple_pipeline.py")) {
            pipelineArguments += " --product-id " + shellQuoted(productId);
        }
        const auto command = "GAME_PRICE_COLLECTION_PROGRESS_PATH=" + shellQuoted(progressPath_) + " python3 " + shellQuoted(
            (project / pipeline).string()) + pipelineArguments +
            " --tracker " + shellQuoted(trackerPath().string()) +
            " --catalog " + shellQuoted(catalogPath()) +
            " --database " + shellQuoted(databasePath()) +
            " --output-dir " + shellQuoted(
                (project / "snapshots/latest").string());
        const auto collectionStartedAt = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        const auto exitCode = std::system(command.c_str());
        const auto pipelineExitCode = WIFEXITED(exitCode)
            ? WEXITSTATUS(exitCode)
            : exitCode;
        std::size_t integrityIssueCount = 0;
        if (pipelineExitCode == 0 || pipelineExitCode == 2) {
            {
                std::lock_guard<std::mutex> lock(mutex_);
                phase_ = "AUDITING";
            }
            try {
                integrityIssueCount = runPriceIntegrityAudit()["issueCount"].asUInt64();
            } catch (const std::exception&) {
                integrityIssueCount = 0;
            }
        }
        std::lock_guard<std::mutex> lock(mutex_);
        integrityIssueCount_ = integrityIssueCount;
        status_ = pipelineExitCode == 0
            ? "SUCCEEDED"
            : pipelineExitCode == 2 ? "PARTIAL" : "FAILED";
        phase_ = "FINISHED";
        if (pipelineExitCode == 2) {
            error_ = store + " collection completed with unavailable products";
        } else if (pipelineExitCode != 0) {
            error_ = store + " collection pipeline failed";
        }
        if (pipelineExitCode != 0 && store == "Epic Games Store") {
            try {
                Database database(databasePath());
                sqlite3_stmt* statement = nullptr;
                const char* sql = "SELECT error_message FROM catalog_product_collection_failures "
                    "WHERE provider = 'EpicGamesStore' AND attempted_at >= datetime(?, 'unixepoch') "
                    "AND (? = '' OR external_product_id = ?) ORDER BY attempted_at DESC LIMIT 1";
                if (sqlite3_prepare_v2(database.handle(), sql, -1, &statement, nullptr) == SQLITE_OK) {
                    sqlite3_bind_int64(statement, 1, collectionStartedAt);
                    sqlite3_bind_text(statement, 2, productId.c_str(), -1, SQLITE_TRANSIENT);
                    sqlite3_bind_text(statement, 3, productId.c_str(), -1, SQLITE_TRANSIENT);
                    if (sqlite3_step(statement) == SQLITE_ROW) {
                        const auto message = sqlite3_column_text(statement, 0);
                        if (message) error_ = reinterpret_cast<const char*>(message);
                    }
                }
                sqlite3_finalize(statement);
            } catch (const std::exception&) {
                // Preserve the pipeline error when failure details cannot be read.
            }
        }
        releaseCollectionLock(lockDescriptor);
    }

    mutable std::mutex mutex_;
    std::uint64_t id_{};
    std::string status_{"IDLE"};
    std::string store_{"Steam"};
    std::string productId_;
    std::string error_;
    std::size_t integrityIssueCount_{};
    std::string progressPath_;
    std::string phase_{"PREPARING"};
};

Json::Value runCatalogSyncCommand(
    const std::filesystem::path& script,
    const std::string& arguments) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto project = projectPath();
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-catalog-sync.json";
    std::string command = "python3 " + shellQuoted(script.string()) +
        " --catalog " + shellQuoted(catalogPath()) +
        " --database " + shellQuoted(databasePath()) + arguments;
    command += " > " + shellQuoted(temporary.string()) + " 2>&1";
    const auto exitCode = std::system(command.c_str());
    std::ifstream input(temporary);
    Json::Value result;
    Json::CharReaderBuilder builder;
    std::string errors;
    const auto parsed = Json::parseFromStream(builder, input, &result, &errors);
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    const bool reportedFailure = parsed && result["provider"].isString() &&
        (result["status"].asString() == "FAILED" ||
         result["status"].asString() == "PARTIAL" ||
         result["status"].asString() == "PARTIAL_FAILURE" ||
         result.isMember("priceCollection"));
    if (!parsed || (exitCode != 0 && !reportedFailure)) {
        throw std::runtime_error("catalog synchronization command failed");
    }
    return result;
}

Json::Value runCatalogSyncTool(bool synchronize, int batchSize) {
    const auto project = projectPath();
    if (synchronize) {
        return runCatalogSyncCommand(
            project / "tools/run_catalog_sync_pipeline.py",
            " --tracker " + shellQuoted(trackerPath().string()) +
            " --output-dir " + shellQuoted(
                (project / "snapshots/latest").string()) +
            " --batch-size " + std::to_string(batchSize));
    }
    return runCatalogSyncCommand(
        project / "tools/sync_steam_catalog.py",
        " --status");
}

Json::Value runSteamCatalogDiscoveryTool() {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-steam-discovery.json";
    const auto script = projectPath() /
        "tools/discover_steam_catalog.py";
    std::string command = "python3 " + shellQuoted(script.string());
    command += " --database " + shellQuoted(databasePath());
    command += " --per-source-limit 100";
    command += " --pages-per-source 2";
    return executeCatalogTool(std::move(command), temporary, true);
}

class SteamCatalogDiscoveryJob {
public:
    SteamCatalogDiscoveryJob() {
        result_["provider"] = "Steam";
        result_["status"] = "IDLE";
    }

    bool start() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (result_["status"].asString() == "RUNNING") {
            return false;
        }
        result_["provider"] = "Steam";
        result_["status"] = "RUNNING";
        result_.removeMember("error");
        std::thread([this]() { run(); }).detach();
        return true;
    }

    Json::Value json() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return result_;
    }

private:
    void run() {
        Json::Value next;
        next["provider"] = "Steam";
        try {
            const auto discovery = runSteamCatalogDiscoveryTool();
            next["status"] = discovery.isMember("status") ?
                discovery["status"] : Json::Value("SUCCEEDED");
            next["queued"] = discovery["queued"];
            next["existing"] = discovery["existing"];
            next["pending"] = discovery["pending"];
            next["retryAfterSeconds"] = discovery["retryAfterSeconds"];
            next["failures"] = discovery["failures"];
        } catch (const std::exception& error) {
            next["status"] = "FAILED";
            next["error"] = error.what();
        }
        std::lock_guard<std::mutex> lock(mutex_);
        result_ = next;
    }

    mutable std::mutex mutex_;
    Json::Value result_;
};

void resolveCatalogReview(
    const std::string& appId,
    const std::string& resolution) {
    const auto project = projectPath();
    runCatalogSyncCommand(
        project / "tools/sync_steam_catalog.py",
        " --resolve-app-id " + appId +
        " --resolution " + resolution);
}

Json::Value requestCatalogGame(const std::string& query) {
    const auto project = projectPath();
    return runCatalogSyncCommand(
        project / "tools/sync_steam_catalog.py",
        " --request-game " + shellQuoted(query));
}

Json::Value adminHealthSummary() {
    const auto project = projectPath();
    return runCatalogSyncCommand(
        project / "tools/admin_health_summary.py",
        "");
}

Json::Value disconnectCatalogProduct(
    const std::string& store,
    const std::string& productId) {
    const auto project = projectPath();
    return runCatalogSyncCommand(
        project / "tools/remove_catalog_product.py",
        " --store " + shellQuoted(store) +
        " --product-id " + shellQuoted(productId) +
        " --apply");
}

Json::Value runMetadataSync(
    bool synchronize,
    const std::string& gameId = {},
    const std::string& resolution = {}) {
    const auto project = projectPath();
    std::string arguments;
    if (!gameId.empty()) {
        arguments += " --resolve-game-id " + shellQuoted(gameId);
        arguments += " --resolution " + shellQuoted(resolution);
    } else if (!synchronize) {
        arguments += " --status";
    }
    return runCatalogSyncCommand(
        project / "tools/sync_steam_metadata.py",
        arguments);
}

Json::Value runMobileCatalogSyncTool(
    const std::string& store,
    bool synchronize,
    int batchSize) {
    const auto project = projectPath();
    std::string arguments = " --store " + shellQuoted(store);
    if (synchronize) {
        arguments += " --batch-size " + std::to_string(batchSize);
    } else {
        arguments += " --status";
    }
    return runCatalogSyncCommand(
        project / "tools/sync_mobile_catalog.py",
        arguments);
}

Json::Value resolveMobileCatalogReview(
    const std::string& store,
    const std::string& productId,
    const std::string& resolution) {
    const auto project = projectPath();
    return runCatalogSyncCommand(
        project / "tools/sync_mobile_catalog.py",
        " --store " + shellQuoted(store) +
        " --resolve-product-id " + shellQuoted(productId) +
        " --resolution " + shellQuoted(resolution));
}

class MobileCatalogSyncJob {
public:
    bool start(const std::string& store, int batchSize) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (running_) {
            return false;
        }
        running_ = true;
        activeStore_ = store;
        std::thread([this, store, batchSize]() {
            run(store, batchSize);
        }).detach();
        return true;
    }

    Json::Value status(const std::string& store) const {
        std::lock_guard<std::mutex> lock(mutex_);
        if (running_ && activeStore_ == store) {
            Json::Value result;
            result["provider"] = store;
            result["status"] = "RUNNING";
            result["pendingReviews"] = Json::arrayValue;
            result["reviewHistory"] = Json::arrayValue;
            result["recentRuns"] = Json::arrayValue;
            return result;
        }
        return runMobileCatalogSyncTool(store, false, 0);
    }

private:
    void run(const std::string& store, int batchSize) {
        try {
            runMobileCatalogSyncTool(store, true, batchSize);
        } catch (const std::exception&) {
        }
        std::lock_guard<std::mutex> lock(mutex_);
        running_ = false;
        activeStore_.clear();
    }

    mutable std::mutex mutex_;
    bool running_{};
    std::string activeStore_;
};

class CatalogSyncJob {
public:
    explicit CatalogSyncJob(GameCatalog& catalog)
        : catalog_(catalog) {
        try {
            result_ = runCatalogSyncTool(false, 0);
        } catch (const std::exception&) {
            result_["provider"] = "Steam";
            result_["status"] = "IDLE";
        }
    }

    bool start(int batchSize) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (result_["status"].asString() == "RUNNING") {
            return false;
        }
        result_["provider"] = "Steam";
        result_["status"] = "RUNNING";
        std::thread([this, batchSize]() { run(batchSize); }).detach();
        return true;
    }

    Json::Value json() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return result_;
    }

    Json::Value refresh() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (result_["status"].asString() != "RUNNING") {
            result_ = runCatalogSyncTool(false, 0);
        }
        return result_;
    }

    bool resolve(const std::string& appId, const std::string& resolution) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (result_["status"].asString() == "RUNNING") {
            return false;
        }
        resolveCatalogReview(appId, resolution);
        result_ = runCatalogSyncTool(false, 0);
        return true;
    }

private:
    void run(int batchSize) {
        Json::Value next;
        try {
            runCatalogSyncTool(true, batchSize);
            next = runCatalogSyncTool(false, 0);
            catalog_.reload(catalogPath());
        } catch (const std::exception& error) {
            next["provider"] = "Steam";
            next["status"] = "FAILED";
            next["error"] = error.what();
        }
        std::lock_guard<std::mutex> lock(mutex_);
        result_ = next;
    }

    GameCatalog& catalog_;
    mutable std::mutex mutex_;
    Json::Value result_;
};

struct OAuthConfig {
    OAuthProvider provider;
    std::string clientId;
    std::string clientSecret;
    std::string authorizeUrl;
    std::string tokenOrigin;
    std::string tokenPath;
    std::string userOrigin;
    std::string userPath;
    std::string scope;
};
std::optional<OAuthConfig> oauthConfig(OAuthProvider provider) {
    OAuthConfig config;
    if(provider==OAuthProvider::Google) config={provider,env("GOOGLE_OAUTH_CLIENT_ID"),env("GOOGLE_OAUTH_CLIENT_SECRET"),"https://accounts.google.com/o/oauth2/v2/auth","https://oauth2.googleapis.com","/token","https://openidconnect.googleapis.com","/v1/userinfo","openid email profile"};
    else if(provider==OAuthProvider::Kakao) config={provider,env("KAKAO_OAUTH_CLIENT_ID"),env("KAKAO_OAUTH_CLIENT_SECRET"),"https://kauth.kakao.com/oauth/authorize","https://kauth.kakao.com","/oauth/token","https://kapi.kakao.com","/v2/user/me","account_email profile_nickname"};
    else config={provider,env("NAVER_OAUTH_CLIENT_ID"),env("NAVER_OAUTH_CLIENT_SECRET"),"https://nid.naver.com/oauth2.0/authorize","https://nid.naver.com","/oauth2.0/token","https://openapi.naver.com","/v1/nid/me",""};
    return config.clientId.empty()||(provider!=OAuthProvider::Kakao&&config.clientSecret.empty())?std::nullopt:std::optional<OAuthConfig>{config};
}
std::string providerPath(OAuthProvider provider) {
    std::string value=toString(provider); value[0]=static_cast<char>(std::tolower(value[0])); return value;
}
std::string callbackUri(OAuthProvider provider) {
    auto base=env("OAUTH_CALLBACK_BASE"); if(base.empty()) base="http://127.0.0.1:8080";
    return base+"/api/oauth/"+providerPath(provider)+"/callback";
}
std::string webAppUrl() { auto value=env("WEB_APP_URL"); return value.empty()?"http://127.0.0.1:5173":value; }
std::string formEncode(const std::map<std::string,std::string>& fields) {
    std::string result; for(const auto& [key,value]:fields){if(!result.empty())result+='&';result+=drogon::utils::urlEncodeComponent(key)+"="+drogon::utils::urlEncodeComponent(value);} return result;
}
std::optional<OAuthProfile> oauthProfile(OAuthProvider provider,const Json::Value& body) {
    OAuthProfile profile; profile.provider=provider;
    if(provider==OAuthProvider::Google){ if(!body["sub"].isString())return std::nullopt; profile.providerUserId=body["sub"].asString(); if(body["email"].isString())profile.email=body["email"].asString(); }
    else if(provider==OAuthProvider::Kakao){ if(!body["id"].isIntegral())return std::nullopt; profile.providerUserId=body["id"].asString(); if(body["kakao_account"]["email"].isString())profile.email=body["kakao_account"]["email"].asString(); }
    else { const auto& value=body["response"]; if(!value["id"].isString())return std::nullopt; profile.providerUserId=value["id"].asString(); if(value["email"].isString())profile.email=value["email"].asString(); }
    return profile;
}

std::optional<Platform> platformFromParameter(const std::string& value) {
    if (value.empty()) {
        return std::nullopt;
    }
    if (value == "Windows") {
        return Platform::Windows;
    }
    if (value == "macOS") {
        return Platform::MacOS;
    }
    if (value == "Linux") {
        return Platform::Linux;
    }
    if (value == "Android") {
        return Platform::Android;
    }
    if (value == "iOS") {
        return Platform::IOS;
    }
    if (value == "iPadOS") {
        return Platform::IPadOS;
    }
    if (value == "Nintendo Switch") {
        return Platform::NintendoSwitch;
    }
    if (value == "Nintendo Switch 2") {
        return Platform::NintendoSwitch2;
    }
    if (value == "PlayStation 4") {
        return Platform::PlayStation4;
    }
    if (value == "PlayStation 5") {
        return Platform::PlayStation5;
    }
    if (value == "Xbox One") {
        return Platform::XboxOne;
    }
    if (value == "Xbox Series X|S") {
        return Platform::XboxSeries;
    }
    if (value == "Meta Quest") {
        return Platform::MetaQuest;
    }
    throw std::invalid_argument("unsupported platform");
}

std::optional<Store> storeFromParameter(const std::string& value) {
    if (value.empty()) {
        return std::nullopt;
    }
    if (value == "Steam") {
        return Store::Steam;
    }
    if (value == "Epic Games Store") {
        return Store::EpicGamesStore;
    }
    if (value == "Nintendo eShop") {
        return Store::NintendoEShop;
    }
    if (value == "PlayStation Store") {
        return Store::PlayStationStore;
    }
    if (value == "Microsoft Store") {
        return Store::MicrosoftStore;
    }
    if (value == "Google Play") {
        return Store::GooglePlay;
    }
    if (value == "Apple App Store") {
        return Store::AppleAppStore;
    }
    if (value == "Ubisoft Store") return Store::UbisoftStore;
    if (value == "GOG") return Store::GOG;
    if (value == "Meta Quest Store") return Store::MetaQuestStore;
    if (value == "EA app") return Store::EAApp;
    if (value == "Battle.net") return Store::BattleNet;
    if (value == "itch.io") return Store::ItchIo;
    if (value == "Humble Store") return Store::HumbleStore;
    throw std::invalid_argument("unsupported store");
}

PriceComparisonCriteria comparisonCriteria(
    const drogon::HttpRequestPtr& request) {
    PriceComparisonCriteria criteria;
    criteria.excludedStores = {Store::EpicGamesStore};
    const auto region = request->getParameter("region");
    const auto edition = request->getParameter("edition");
    const auto offerType = request->getParameter("offerType");
    const auto currency = request->getParameter("currency");
    const auto platform = request->getParameter("platform");
    const auto includeForeignCurrencies =
        request->getParameter("includeForeignCurrencies");

    if (!region.empty() && region != "KR") {
        throw std::invalid_argument("region must be KR");
    }
    if (!edition.empty()) {
        if (edition == "Standard") criteria.edition = GameEdition::Standard;
        else if (edition == "Deluxe") criteria.edition = GameEdition::Deluxe;
        else if (edition == "Switch2Edition") {
            criteria.edition = GameEdition::Switch2Edition;
        } else throw std::invalid_argument(
            "edition must be Standard, Deluxe, or Switch2Edition");
    }
    if (!offerType.empty()) {
        criteria.includeBundles = false;
        if (offerType == "BaseGame") criteria.offerType = OfferType::BaseGame;
        else if (offerType == "DLC") criteria.offerType = OfferType::DLC;
        else if (offerType == "Bundle") criteria.offerType = OfferType::Bundle;
        else if (offerType == "Subscription") {
            criteria.offerType = OfferType::Subscription;
        } else if (offerType == "UpgradePack") {
            criteria.offerType = OfferType::UpgradePack;
        } else {
            throw std::invalid_argument(
                "offerType must be BaseGame, DLC, Bundle, Subscription, or UpgradePack");
        }
    }
    if (currency == "USD") criteria.currency = Currency::USD;
    else if (currency == "EUR") criteria.currency = Currency::EUR;
    else if (currency == "GBP") criteria.currency = Currency::GBP;
    else if (currency == "JPY") criteria.currency = Currency::JPY;
    else if (!currency.empty() && currency != "KRW")
        throw std::invalid_argument("unsupported currency");
    if (!includeForeignCurrencies.empty()) {
        if (includeForeignCurrencies == "true" ||
            includeForeignCurrencies == "1") {
            criteria.includeForeignCurrencies = true;
        } else if (includeForeignCurrencies != "false" &&
                   includeForeignCurrencies != "0") {
            throw std::invalid_argument(
                "includeForeignCurrencies must be true or false");
        }
    }
    const auto parsedPlatform = platformFromParameter(platform);
    if (parsedPlatform) {
        criteria.platform = *parsedPlatform;
    }
    return criteria;
}

std::string bearerToken(const drogon::HttpRequestPtr& request) {
    const auto header = request->getHeader("Authorization");
    if(header.rfind("Bearer ",0)==0)return header.substr(7);
    return request->getCookie("game_price_session");
}

void setSessionCookie(const HttpResponsePtr& response,const std::string& token) {
    std::string cookie="game_price_session="+token+"; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000";
    const char* secure=std::getenv("COOKIE_SECURE"); if(secure&&std::string(secure)=="true")cookie+="; Secure";
    response->addHeader("Set-Cookie",cookie);
}
void clearSessionCookie(const HttpResponsePtr& response) {
    response->addHeader("Set-Cookie","game_price_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0");
}

std::optional<UserAccount> authenticatedUser(
    const drogon::HttpRequestPtr& request, const AuthService& auth) {
    const auto token = bearerToken(request);
    return token.empty() ? std::nullopt : auth.authenticate(token);
}

HttpResponsePtr adminAccessError(
    const drogon::HttpRequestPtr& request,
    const AuthService& auth) {
    if (!catalogAdminEnabled()) {
        return jsonError(
            drogon::k403Forbidden,
            "catalog admin is disabled");
    }
    const auto user = authenticatedUser(request, auth);
    if (!user) {
        return jsonError(
            drogon::k401Unauthorized,
            "administrator authentication required");
    }
    if (user->role != UserRole::Admin) {
        return jsonError(
            drogon::k403Forbidden,
            "administrator role required");
    }
    return nullptr;
}

Json::Value authJson(const AuthResult& result) {
    Json::Value json;
    json["user"]["id"] = Json::Int64(result.user.id);
    json["user"]["email"] = result.user.email;
    json["user"]["role"] = toString(result.user.role);
    json["token"] = result.token;
    return json;
}

Json::Value adminUserJson(const AdminUserSummary& user) {
    Json::Value json;
    json["id"] = Json::Int64(user.id);
    json["email"] = user.email;
    json["role"] = toString(user.role);
    json["status"] = user.active ? "ACTIVE" : "SUSPENDED";
    json["createdAt"] = user.createdAt;
    if (user.lastLoginAt) {
        json["lastLoginAt"] = *user.lastLoginAt;
    }
    if (user.suspensionReason) {
        json["suspensionReason"] = *user.suspensionReason;
    }
    json["favoriteCount"] = Json::Int64(user.favoriteCount);
    json["alertCount"] = Json::Int64(user.alertCount);
    return json;
}

Json::Value preferencesJson(const UserPreferences& preferences) {
    Json::Value json;
    json["emailNotificationsEnabled"] = preferences.emailNotificationsEnabled;
    json["region"] = preferences.region;
    json["currency"] = preferences.currency;
    return json;
}

}  // namespace

int main() {
    using namespace game_price;

    try {
        validateRuntimeConfiguration();
        Database database(databasePath());
        StoreProductRepository repository(database);
        repository.initializeSchema();
        GameCatalog catalog(catalogPath());
        GameQueryService queryService(catalog, repository);
        AccountRepository accountRepository(database);
        AuthService authService(accountRepository);
        OAuthService oauthService(accountRepository);
        CatalogCollectionJob catalogCollectionJob;
        SteamCatalogDiscoveryJob steamCatalogDiscoveryJob;
        CatalogSyncJob catalogSyncJob(catalog);
        MobileCatalogSyncJob mobileCatalogSyncJob;
        std::mutex catalogReloadMutex;
        std::optional<std::pair<std::filesystem::file_time_type, std::uintmax_t>> catalogRevision;
        const auto catalogFile = catalogPath();

        drogon::app().registerPreRoutingAdvice(
            [&catalog, &catalogReloadMutex, &catalogRevision, catalogFile](const drogon::HttpRequestPtr& request,
               drogon::AdviceCallback&& callback,
               drogon::AdviceChainCallback&& next) {
                if (request->method() == drogon::Options) {
                    callback(jsonResponse(Json::Value{}));
                    return;
                }
                if (request->path().rfind("/api/", 0) == 0) {
                    std::lock_guard<std::mutex> lock(catalogReloadMutex);
                    std::error_code fileError;
                    const auto modified = std::filesystem::last_write_time(catalogFile, fileError);
                    if (!fileError) {
                        const auto size = std::filesystem::file_size(catalogFile, fileError);
                        const auto revision = std::make_pair(modified, size);
                        if (!fileError && (!catalogRevision || *catalogRevision != revision)) {
                            catalogRevision = revision;
                            try {
                                // Background collectors replace the catalog atomically.
                                // reload validates first, then swaps under its reader lock.
                                catalog.reload(catalogFile);
                            } catch (const std::exception& error) {
                                std::cerr << "Catalog refresh failed; retaining last valid catalog: "
                                          << error.what() << '\n';
                            }
                        }
                    }
                }
                next();
            });

        const auto registerAuthHandler = [&authService,&accountRepository](bool registration) {
            return [&authService,&accountRepository,registration](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto body = request->getJsonObject();
                if (!body || !(*body)["email"].isString() || !(*body)["password"].isString()) {
                    callback(jsonError(drogon::k400BadRequest, "email and password are required"));
                    return;
                }
                try {
                    if (registration) {
                        const auto result=authService.registerUser((*body)["email"].asString(),(*body)["password"].asString());
                        auto response=jsonResponse(authJson(result),drogon::k201Created);
                        setSessionCookie(response,result.token);callback(response);
                    } else {
                        auto loginEmail=(*body)["email"].asString();std::transform(loginEmail.begin(),loginEmail.end(),loginEmail.begin(),[](unsigned char value){return static_cast<char>(std::tolower(value));});const auto clientKey=request->peerAddr().toIp();
                        if(accountRepository.isLoginRateLimited(loginEmail,clientKey)){callback(jsonError(drogon::k429TooManyRequests,"too many login attempts; try again later"));return;}
                        const auto result=authService.login(loginEmail,(*body)["password"].asString());
                        if(!result){accountRepository.recordLoginFailure(loginEmail,clientKey);callback(jsonError(drogon::k401Unauthorized,"invalid credentials"));}
                        else {accountRepository.clearLoginFailures(loginEmail,clientKey);auto response=jsonResponse(authJson(*result));setSessionCookie(response,result->token);callback(response);}
                    }
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                } catch (const std::exception&) {
                    callback(jsonError(drogon::k409Conflict, "account could not be created"));
                }
            };
        };
        drogon::app().registerHandler("/api/auth/register", registerAuthHandler(true), {drogon::Post});
        drogon::app().registerHandler("/api/auth/login", registerAuthHandler(false), {drogon::Post});
        drogon::app().registerHandler(
            "/api/auth/password-reset/request",
            [&authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto body = request->getJsonObject();
                if (!body || !(*body)["email"].isString()) {
                    callback(jsonError(drogon::k400BadRequest, "email is required"));
                    return;
                }
                try {
                    authService.requestPasswordReset(
                        (*body)["email"].asString(),
                        webAppUrl());
                    Json::Value response;
                    response["message"] =
                        "If the account exists, a password reset email was queued.";
                    callback(jsonResponse(response, drogon::k202Accepted));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                }
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/auth/password-reset/confirm",
            [&authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto body = request->getJsonObject();
                if (!body || !(*body)["token"].isString() ||
                    !(*body)["password"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "token and password are required"));
                    return;
                }
                try {
                    if (!authService.resetPassword(
                            (*body)["token"].asString(),
                            (*body)["password"].asString())) {
                        callback(jsonError(
                            drogon::k400BadRequest,
                            "password reset link is invalid or expired"));
                        return;
                    }
                    Json::Value response;
                    response["message"] = "password was reset";
                    auto httpResponse = jsonResponse(response);
                    clearSessionCookie(httpResponse);
                    callback(httpResponse);
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                }
            },
            {drogon::Post});

        for (const auto provider : {OAuthProvider::Google, OAuthProvider::Kakao, OAuthProvider::Naver}) {
            const auto path=providerPath(provider);
            drogon::app().registerHandler(
                "/api/oauth/"+path+"/start",
                [provider,&accountRepository,&authService](const drogon::HttpRequestPtr& request,
                    std::function<void(const HttpResponsePtr&)>&& callback) {
                    const auto config=oauthConfig(provider);
                    if(!config){callback(jsonError(drogon::k503ServiceUnavailable,"OAuth provider is not configured"));return;}
                    std::optional<std::int64_t> linkUserId;
                    if(request->getParameter("link")=="true"){
                        const auto user=authenticatedUser(request,authService);
                        if(!user){callback(jsonError(drogon::k401Unauthorized,"authentication required for account linking"));return;}
                        linkUserId=user->id;
                    }
                    const auto state=accountRepository.createOAuthState(provider,linkUserId);
                    std::map<std::string,std::string> query{{"client_id",config->clientId},{"redirect_uri",callbackUri(provider)},{"response_type","code"},{"state",state}};
                    if(!config->scope.empty())query["scope"]=config->scope;
                    Json::Value response; response["authorizationUrl"]=config->authorizeUrl+"?"+formEncode(query);
                    callback(jsonResponse(response));
                }, {drogon::Get});
            drogon::app().registerHandler(
                "/api/oauth/"+path+"/callback",
                [provider,&accountRepository,&oauthService](const drogon::HttpRequestPtr& request,
                    std::function<void(const HttpResponsePtr&)>&& callback) {
                    const auto config=oauthConfig(provider); const auto code=request->getParameter("code"); const auto state=request->getParameter("state");
                    if(!config||code.empty()||state.empty()){callback(jsonError(drogon::k400BadRequest,"invalid OAuth callback"));return;}
                    const auto linkUser=accountRepository.consumeOAuthState(provider,state);
                    if(!linkUser){callback(jsonError(drogon::k400BadRequest,"invalid or expired OAuth state"));return;}
                    auto finalCallback=std::make_shared<std::function<void(const HttpResponsePtr&)>>(std::move(callback));
                    auto tokenClient=drogon::HttpClient::newHttpClient(config->tokenOrigin);
                    auto tokenRequest=drogon::HttpRequest::newHttpRequest(); tokenRequest->setMethod(drogon::Post); tokenRequest->setPath(config->tokenPath);
                    tokenRequest->addHeader("Content-Type","application/x-www-form-urlencoded");
                    std::map<std::string,std::string> tokenFields{{"grant_type","authorization_code"},{"client_id",config->clientId},{"redirect_uri",callbackUri(provider)},{"code",code}};
                    if(!config->clientSecret.empty())tokenFields["client_secret"]=config->clientSecret;
                    tokenRequest->setBody(formEncode(tokenFields));
                    tokenClient->sendRequest(tokenRequest,[config=*config,provider,linkUser,&oauthService,finalCallback](drogon::ReqResult result,const HttpResponsePtr& response){
                        if(result!=drogon::ReqResult::Ok||!response||!response->getJsonObject()||!(*response->getJsonObject())["access_token"].isString()){
                            (*finalCallback)(jsonError(drogon::k502BadGateway,"OAuth token exchange failed"));return;
                        }
                        const auto accessToken=(*response->getJsonObject())["access_token"].asString();
                        auto userClient=drogon::HttpClient::newHttpClient(config.userOrigin);
                        auto userRequest=drogon::HttpRequest::newHttpRequest(); userRequest->setMethod(drogon::Get); userRequest->setPath(config.userPath);
                        userRequest->addHeader("Authorization","Bearer "+accessToken);
                        if(provider==OAuthProvider::Naver){userRequest->addHeader("X-Naver-Client-Id",config.clientId);userRequest->addHeader("X-Naver-Client-Secret",config.clientSecret);}
                        userClient->sendRequest(userRequest,[provider,linkUser,&oauthService,finalCallback](drogon::ReqResult userResult,const HttpResponsePtr& userResponse){
                            if(userResult!=drogon::ReqResult::Ok||!userResponse||!userResponse->getJsonObject()){
                                (*finalCallback)(jsonError(drogon::k502BadGateway,"OAuth profile request failed"));return;
                            }
                            const auto profile=oauthProfile(provider,*userResponse->getJsonObject());
                            if(!profile){(*finalCallback)(jsonError(drogon::k502BadGateway,"OAuth profile is invalid"));return;}
                            try {
                                if(*linkUser!=0){oauthService.linkIdentity(*linkUser,*profile);(*finalCallback)(HttpResponse::newRedirectionResponse(webAppUrl()+"/#oauth_linked="+providerPath(provider)));}
                                else {const auto auth=oauthService.completeLogin(*profile);auto redirect=HttpResponse::newRedirectionResponse(webAppUrl()+"/#oauth=success");setSessionCookie(redirect,auth.token);(*finalCallback)(redirect);}
                            } catch(const std::exception& error){(*finalCallback)(jsonError(drogon::k409Conflict,error.what()));}
                        },10);
                    },10);
                }, {drogon::Get});
        }

        drogon::app().registerHandler(
            "/api/external-identities",
            [&authService,&accountRepository](const drogon::HttpRequestPtr& request,std::function<void(const HttpResponsePtr&)>&& callback){
                const auto user=authenticatedUser(request,authService); if(!user){callback(jsonError(drogon::k401Unauthorized,"authentication required"));return;}
                Json::Value response; response["identities"]=Json::arrayValue;
                for(const auto& identity:accountRepository.findExternalIdentities(user->id)){Json::Value item;item["id"]=Json::Int64(identity.id);item["provider"]=toString(identity.provider);if(identity.email)item["email"]=*identity.email;response["identities"].append(std::move(item));}
                callback(jsonResponse(response));
            }, {drogon::Get});
        drogon::app().registerHandler(
            "/api/external-identities/{1}",
            [&authService,&accountRepository](const drogon::HttpRequestPtr& request,std::function<void(const HttpResponsePtr&)>&& callback,std::int64_t id){
                const auto user=authenticatedUser(request,authService); if(!user){callback(jsonError(drogon::k401Unauthorized,"authentication required"));return;}
                try{accountRepository.deleteExternalIdentity(user->id,id);callback(jsonResponse(Json::Value{}));}
                catch(const std::invalid_argument& error){callback(jsonError(drogon::k400BadRequest,error.what()));}
            }, {drogon::Delete});

        drogon::app().registerHandler(
            "/api/auth/me",
            [&authService](const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) {
                    callback(jsonError(
                        drogon::k401Unauthorized,
                        "authentication required"));
                    return;
                }
                Json::Value json;
                json["id"] = Json::Int64(user->id);
                json["email"] = user->email;
                json["role"] = toString(user->role);
                callback(jsonResponse(json));
            }, {drogon::Get});
        drogon::app().registerHandler(
            "/api/auth/logout",
            [&authService](const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto token = bearerToken(request);
                if (!token.empty()) authService.logout(token);
                auto response=jsonResponse(Json::Value{});clearSessionCookie(response);callback(response);
            }, {drogon::Post});

        drogon::app().registerHandler(
            "/api/favorites",
            [&authService, &accountRepository, &catalog](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) {
                    callback(jsonError(
                        drogon::k401Unauthorized,
                        "authentication required"));
                    return;
                }
                Json::Value response;
                response["games"] = Json::arrayValue;
                for (const auto& gameId :
                     accountRepository.findFavoriteGameIds(user->id)) {
                    const auto game = catalog.findById(gameId);
                    if (game) {
                        response["games"].append(gameJson(*game));
                    }
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/favorites",
            [&authService, &accountRepository, &catalog](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) {
                    callback(jsonError(
                        drogon::k401Unauthorized,
                        "authentication required"));
                    return;
                }
                const auto body = request->getJsonObject();
                if (!body || !(*body)["gameId"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "gameId is required"));
                    return;
                }
                const auto gameId = (*body)["gameId"].asString();
                if (!catalog.findById(gameId)) {
                    callback(jsonError(drogon::k404NotFound, "game not found"));
                    return;
                }
                const auto created =
                    accountRepository.addFavoriteGame(user->id, gameId);
                Json::Value response;
                response["gameId"] = gameId;
                callback(jsonResponse(
                    response,
                    created ? drogon::k201Created : drogon::k200OK));
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/favorites/{1}",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                const std::string& gameId) {
                const auto user = authenticatedUser(request, authService);
                if (!user) {
                    callback(jsonError(
                        drogon::k401Unauthorized,
                        "authentication required"));
                    return;
                }
                if (!accountRepository.deleteFavoriteGame(user->id, gameId)) {
                    callback(jsonError(
                        drogon::k404NotFound,
                        "favorite game not found"));
                    return;
                }
                callback(jsonResponse(Json::Value{}));
            },
            {drogon::Delete});

        drogon::app().registerHandler(
            "/api/account/preferences",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) {
                    callback(jsonError(
                        drogon::k401Unauthorized,
                        "authentication required"));
                    return;
                }
                callback(jsonResponse(
                    preferencesJson(accountRepository.findPreferences(user->id))));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/account/preferences",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) {
                    callback(jsonError(
                        drogon::k401Unauthorized,
                        "authentication required"));
                    return;
                }
                const auto body = request->getJsonObject();
                if (!body ||
                    !(*body)["emailNotificationsEnabled"].isBool() ||
                    !(*body)["region"].isString() ||
                    !(*body)["currency"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "emailNotificationsEnabled, region, and currency are required"));
                    return;
                }
                try {
                    const UserPreferences preferences{
                        (*body)["emailNotificationsEnabled"].asBool(),
                        (*body)["region"].asString(),
                        (*body)["currency"].asString()};
                    callback(jsonResponse(preferencesJson(
                        accountRepository.updatePreferences(
                            user->id,
                            preferences))));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                }
            },
            {drogon::Patch});

        drogon::app().registerHandler(
            "/api/account",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) {
                    callback(jsonError(
                        drogon::k401Unauthorized,
                        "authentication required"));
                    return;
                }
                const auto body = request->getJsonObject();
                const auto confirmation =
                    body && (*body)["confirmation"].isString()
                    ? (*body)["confirmation"].asString()
                    : std::string{};
                if (confirmation != user->email) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "account email confirmation does not match"));
                    return;
                }
                if (!accountRepository.deleteUser(user->id)) {
                    callback(jsonError(
                        drogon::k404NotFound,
                        "account not found"));
                    return;
                }
                auto response = jsonResponse(Json::Value{});
                clearSessionCookie(response);
                callback(response);
            },
            {drogon::Delete});

        drogon::app().registerHandler(
            "/api/alert-rules",
            [&authService, &accountRepository,&catalog](const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) { callback(jsonError(drogon::k401Unauthorized, "authentication required")); return; }
                Json::Value response; response["rules"] = Json::arrayValue;
                for (const auto& rule : accountRepository.findRules(user->id)) {
                    Json::Value item; item["id"] = Json::Int64(rule.id); item["gameId"] = rule.gameId;
                    const auto game=catalog.findById(rule.gameId);if(game)item["gameTitle"]=game->title;
                    item["type"] = toString(rule.type); item["active"] = rule.active;
                    if (rule.targetPriceMinor) item["targetPriceMinor"] = Json::Int64(*rule.targetPriceMinor);
                    if(rule.platform)item["platform"]=toString(*rule.platform);
                    response["rules"].append(std::move(item));
                }
                callback(jsonResponse(response));
            }, {drogon::Get});
        drogon::app().registerHandler(
            "/api/alert-rules",
            [&authService, &accountRepository, &catalog](const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) { callback(jsonError(drogon::k401Unauthorized, "authentication required")); return; }
                const auto body = request->getJsonObject();
                if (!body || !(*body)["gameId"].isString() || !(*body)["type"].isString()) {
                    callback(jsonError(drogon::k400BadRequest, "gameId and type are required")); return;
                }
                const auto game=catalog.findById((*body)["gameId"].asString());
                if (!game) {
                    callback(jsonError(drogon::k404NotFound, "game not found")); return;
                }
                try {
                    const auto type = alertRuleTypeFromString((*body)["type"].asString());
                    std::optional<std::int64_t> target;
                    if ((*body).isMember("targetPriceMinor")){
                        if(!(*body)["targetPriceMinor"].isIntegral()){callback(jsonError(drogon::k400BadRequest,"targetPriceMinor must be an integer"));return;}
                        target=(*body)["targetPriceMinor"].asInt64();
                    }
                    std::optional<Platform> platform;
                    if((*body).isMember("platform")){
                        if(!(*body)["platform"].isString()){callback(jsonError(drogon::k400BadRequest,"platform must be a string"));return;}
                        platform = platformFromParameter(
                            (*body)["platform"].asString());
                        if(std::find(game->supportedPlatforms.begin(),game->supportedPlatforms.end(),*platform)==game->supportedPlatforms.end()){callback(jsonError(drogon::k400BadRequest,"platform is not supported by game"));return;}
                    }
                    const auto rule = accountRepository.addRule(user->id, (*body)["gameId"].asString(), type, target,platform);
                    Json::Value response; response["id"] = Json::Int64(rule.id);
                    callback(jsonResponse(response, drogon::k201Created));
                } catch (const std::exception& error) {
                    callback(jsonError(std::string(error.what())=="alert rule already exists"?drogon::k409Conflict:drogon::k400BadRequest, error.what()));
                }
            }, {drogon::Post});
        drogon::app().registerHandler(
            "/api/alert-rules/{1}",
            [&authService, &accountRepository](const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback, std::int64_t id) {
                const auto user = authenticatedUser(request, authService);
                if (!user) { callback(jsonError(drogon::k401Unauthorized, "authentication required")); return; }
                if(!accountRepository.deleteRule(user->id,id)){callback(jsonError(drogon::k404NotFound,"alert rule not found"));return;}callback(jsonResponse(Json::Value{}));
            }, {drogon::Delete});
        drogon::app().registerHandler(
            "/api/notifications",
            [&authService, &accountRepository](const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto user = authenticatedUser(request, authService);
                if (!user) { callback(jsonError(drogon::k401Unauthorized, "authentication required")); return; }
                Json::Value response; response["notifications"] = Json::arrayValue;
                for (const auto& value : accountRepository.findNotifications(user->id)) {
                    Json::Value item; item["id"] = Json::Int64(value.id); item["gameId"] = value.gameId;
                    item["store"] = value.store; item["productId"] = value.productId;
                    item["price"]["minorAmount"] = Json::Int64(value.priceMinor); item["price"]["currency"] = value.currency;
                    item["message"] = value.message; item["createdAt"] = value.createdAt; item["read"] = value.read;
                    response["notifications"].append(std::move(item));
                }
                callback(jsonResponse(response));
            }, {drogon::Get});
        drogon::app().registerHandler(
            "/api/notifications/{1}/read",
            [&authService, &accountRepository](const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback, std::int64_t id) {
                const auto user = authenticatedUser(request, authService);
                if (!user) { callback(jsonError(drogon::k401Unauthorized, "authentication required")); return; }
                if(!accountRepository.markNotificationRead(user->id,id)){callback(jsonError(drogon::k404NotFound,"notification not found"));return;}callback(jsonResponse(Json::Value{}));
            }, {drogon::Patch});

        drogon::app().registerHandler(
            "/api/admin/catalog/status",
            [&authService](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                Json::Value response;
                const auto user = authenticatedUser(request, authService);
                response["enabled"] = catalogAdminEnabled() &&
                    user &&
                    user->role == UserRole::Admin;
                callback(jsonResponse(response));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/health",
            [&authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                try {
                    callback(jsonResponse(adminHealthSummary()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/users",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto query = request->getParameter("q");
                const auto status = request->getParameter("status");
                const auto role = request->getParameter("role");
                const auto sort = request->getParameter("sort");
                if (query.size() > 254) {
                    callback(jsonError(drogon::k400BadRequest, "query is too long"));
                    return;
                }
                if (!status.empty() && status != "ACTIVE" && status != "SUSPENDED") {
                    callback(jsonError(drogon::k400BadRequest, "unsupported status"));
                    return;
                }
                if (!role.empty() && role != "USER" && role != "ADMIN") {
                    callback(jsonError(drogon::k400BadRequest, "unsupported role"));
                    return;
                }
                if (!sort.empty() && sort != "NEWEST" && sort != "OLDEST" &&
                    sort != "EMAIL_ASC" && sort != "EMAIL_DESC") {
                    callback(jsonError(drogon::k400BadRequest, "unsupported sort"));
                    return;
                }
                int page = 1;
                int pageSize = 20;
                try {
                    if (!request->getParameter("page").empty()) {
                        page = std::stoi(request->getParameter("page"));
                    }
                    if (!request->getParameter("pageSize").empty()) {
                        pageSize = std::stoi(request->getParameter("pageSize"));
                    }
                } catch (const std::exception&) {
                    callback(jsonError(drogon::k400BadRequest, "invalid pagination"));
                    return;
                }
                if (page < 1 || pageSize < 1 || pageSize > 100) {
                    callback(jsonError(drogon::k400BadRequest, "invalid pagination"));
                    return;
                }
                Json::Value response;
                response["users"] = Json::arrayValue;
                for (const auto& user : accountRepository.findUsers(
                         query,
                         status,
                         role,
                         sort,
                         pageSize,
                         (page - 1) * pageSize)) {
                    response["users"].append(adminUserJson(user));
                }
                response["page"] = page;
                response["pageSize"] = pageSize;
                response["total"] = Json::Int64(
                    accountRepository.countUsers(query, status, role));
                callback(jsonResponse(response));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/users/{1}",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                std::int64_t userId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto user = accountRepository.findUserForAdministration(userId);
                if (!user) {
                    callback(jsonError(drogon::k404NotFound, "user not found"));
                    return;
                }
                callback(jsonResponse(adminUserJson(*user)));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/users/{1}/status",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                std::int64_t userId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto actor = authenticatedUser(request, authService);
                const auto body = request->getJsonObject();
                if (!actor || !body || !(*body)["active"].isBool()) {
                    callback(jsonError(drogon::k400BadRequest, "active is required"));
                    return;
                }
                const bool active = (*body)["active"].asBool();
                std::optional<std::string> reason;
                if (!active) {
                    if (!(*body)["reason"].isString()) {
                        callback(jsonError(
                            drogon::k400BadRequest,
                            "suspension reason is required"));
                        return;
                    }
                    reason = (*body)["reason"].asString();
                    if (reason->empty() || reason->size() > 500) {
                        callback(jsonError(
                            drogon::k400BadRequest,
                            "suspension reason must be between 1 and 500 characters"));
                        return;
                    }
                }
                try {
                    if (!accountRepository.setUserActive(
                            actor->id,
                            userId,
                            active,
                            reason)) {
                        callback(jsonError(drogon::k404NotFound, "user not found"));
                        return;
                    }
                    callback(jsonResponse(adminUserJson(
                        *accountRepository.findUserForAdministration(userId))));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                }
            },
            {drogon::Patch});
        drogon::app().registerHandler(
            "/api/admin/users/{1}/password-reset",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                std::int64_t userId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto actor = authenticatedUser(request, authService);
                const auto user = accountRepository.findUserForAdministration(userId);
                if (!actor || !user) {
                    callback(jsonError(drogon::k404NotFound, "user not found"));
                    return;
                }
                authService.requestPasswordReset(user->email, webAppUrl());
                accountRepository.recordAdminUserAction(
                    actor->id,
                    userId,
                    "SEND_PASSWORD_RESET");
                Json::Value response;
                response["message"] = "password reset email was queued";
                callback(jsonResponse(response, drogon::k202Accepted));
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/users/audits",
            [&authService, &accountRepository](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                Json::Value response;
                response["audits"] = Json::arrayValue;
                for (const auto& audit : accountRepository.findAdminUserAudits(100)) {
                    Json::Value item;
                    item["id"] = Json::Int64(audit.id);
                    item["actorUserId"] = Json::Int64(audit.actorUserId);
                    item["targetUserId"] = Json::Int64(audit.targetUserId);
                    item["actorEmail"] = audit.actorEmail;
                    item["targetEmail"] = audit.targetEmail;
                    item["action"] = audit.action;
                    item["createdAt"] = audit.createdAt;
                    if (audit.detail) {
                        item["detail"] = *audit.detail;
                    }
                    response["audits"].append(std::move(item));
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/integrity",
            [&authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                try {
                    callback(jsonResponse(runPriceIntegrityAudit()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/metadata-sync",
            [&authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                try {
                    callback(jsonResponse(runMetadataSync(false)));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/metadata-sync",
            [&authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                try {
                    callback(jsonResponse(runMetadataSync(true)));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k502BadGateway,
                        error.what()));
                }
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/metadata-sync/{1}",
            [&catalog, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                const std::string& gameId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                const auto resolution = body && (*body)["resolution"].isString()
                    ? (*body)["resolution"].asString()
                    : std::string{};
                if (!validCanonicalGameId(gameId) ||
                    (resolution != "APPROVED" && resolution != "REJECTED")) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "valid game ID and resolution are required"));
                    return;
                }
                try {
                    callback(jsonResponse(runMetadataSync(
                        false,
                        gameId,
                        resolution)));
                    if (resolution == "APPROVED") {
                        catalog.reload(catalogPath());
                    }
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        error.what()));
                }
            },
            {drogon::Patch});
        drogon::app().registerHandler(
            "/api/admin/catalog/games/{1}/metadata",
            [&catalog, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                const std::string& gameId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                if (!validCanonicalGameId(gameId)) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "invalid canonical game ID"));
                    return;
                }
                const auto body = request->getJsonObject();
                if (!body || !(*body)["metadata"].isObject()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "metadata object is required"));
                    return;
                }
                const auto apply = (*body)["apply"].isBool() &&
                    (*body)["apply"].asBool();
                try {
                    Json::Value response;
                    response["result"] = runCatalogMetadataUpdate(
                        gameId,
                        (*body)["metadata"],
                        apply);
                    response["applied"] = apply;
                    if (apply) {
                        catalog.reload(catalogPath());
                    }
                    callback(jsonResponse(response));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Patch});
        drogon::app().registerHandler(
            "/api/admin/catalog/products/{1}/{2}",
            [&catalog, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                const std::string& store,
                const std::string& productId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const std::set<std::string> supportedStores{
                    "Steam",
                    "GooglePlay",
                    "AppleAppStore",
                    "EpicGamesStore",
                    "NintendoEShop",
                    "PlayStationStore",
                    "MicrosoftStore",
                    "UbisoftStore",
                    "GOG",
                    "MetaQuestStore",
                    "EAApp",
                    "BattleNet",
                    "ItchIo",
                    "HumbleStore",
                };
                if (supportedStores.count(store) == 0 || productId.empty()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "valid store and product ID are required"));
                    return;
                }
                try {
                    const auto result = disconnectCatalogProduct(
                        store,
                        productId);
                    catalog.reload(catalogPath());
                    callback(jsonResponse(result));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        error.what()));
                }
            },
            {drogon::Delete});
        drogon::app().registerHandler(
            "/api/admin/catalog/audits",
            [&authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                auto limit = 50;
                const auto value = request->getParameter("limit");
                if (!value.empty()) {
                    try {
                        limit = std::stoi(value);
                    } catch (const std::exception&) {
                        callback(jsonError(
                            drogon::k400BadRequest,
                            "limit must be an integer"));
                        return;
                    }
                }
                if (limit < 1 || limit > 200) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "limit must be between 1 and 200"));
                    return;
                }
                try {
                    callback(jsonResponse(runCatalogAuditList(limit)));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/steam",
            [&catalog, &authService](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                if (!body || !(*body)["appId"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "appId is required"));
                    return;
                }
                const auto appId = (*body)["appId"].asString();
                const auto gameId = (*body)["gameId"].isString()
                    ? (*body)["gameId"].asString()
                    : std::string{};
                if (!validSteamAppId(appId) ||
                    !validCanonicalGameId(gameId)) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "invalid appId or gameId"));
                    return;
                }
                const auto apply = (*body)["apply"].isBool() &&
                    (*body)["apply"].asBool();
                try {
                    Json::Value response;
                    response["game"] = runCatalogImport(appId, gameId, apply);
                    response["applied"] = apply;
                    if (apply) {
                        catalog.reload(catalogPath());
                    }
                    response["requiresApiRestart"] = false;
                    callback(jsonResponse(response));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/candidates",
            [&authService](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto store = request->getParameter("store");
                const auto query = request->getParameter("query");
                if (query.empty() || query.size() > 100) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "query must contain between 1 and 100 characters"));
                    return;
                }
                try {
                    callback(jsonResponse(runStoreSearch(store, query)));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k502BadGateway,
                        error.what()));
                }
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/google-play",
            [&catalog, &authService](const drogon::HttpRequestPtr& request,
                       std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                if (!body || !(*body)["packageName"].isString() ||
                    !(*body)["gameId"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "packageName and gameId are required"));
                    return;
                }
                const auto packageName = (*body)["packageName"].asString();
                const auto gameId = (*body)["gameId"].asString();
                if (!validGooglePlayPackage(packageName) || gameId.empty() ||
                    !validCanonicalGameId(gameId)) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "invalid packageName or gameId"));
                    return;
                }
                const auto apply = (*body)["apply"].isBool() &&
                    (*body)["apply"].asBool();
                const auto acknowledgeReview =
                    (*body)["acknowledgeReview"].isBool() &&
                    (*body)["acknowledgeReview"].asBool();
                try {
                    Json::Value response;
                    response["game"] = runGooglePlayCatalogImport(
                        packageName,
                        gameId,
                        apply,
                        acknowledgeReview);
                    response["applied"] = apply;
                    if (apply) {
                        catalog.reload(catalogPath());
                    }
                    response["requiresApiRestart"] = false;
                    callback(jsonResponse(response));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/apple",
            [&catalog, &authService](const drogon::HttpRequestPtr& request,
                       std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                if (!body || !(*body)["trackId"].isString() ||
                    !(*body)["gameId"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "trackId and gameId are required"));
                    return;
                }
                const auto trackId = (*body)["trackId"].asString();
                const auto gameId = (*body)["gameId"].asString();
                if (!validAppleTrackId(trackId) || gameId.empty() ||
                    !validCanonicalGameId(gameId)) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "invalid trackId or gameId"));
                    return;
                }
                const auto apply = (*body)["apply"].isBool() &&
                    (*body)["apply"].asBool();
                const auto acknowledgeReview =
                    (*body)["acknowledgeReview"].isBool() &&
                    (*body)["acknowledgeReview"].asBool();
                try {
                    Json::Value response;
                    response["game"] = runAppleCatalogImport(
                        trackId,
                        gameId,
                        apply,
                        acknowledgeReview);
                    response["applied"] = apply;
                    if (apply) {
                        catalog.reload(catalogPath());
                    }
                    response["requiresApiRestart"] = false;
                    callback(jsonResponse(response));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/storefront",
            [&catalog, &authService](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                if (!body || !(*body)["store"].isString() ||
                    !(*body)["productUrl"].isString() ||
                    !(*body)["gameId"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "store, productUrl and gameId are required"));
                    return;
                }
                const auto store = (*body)["store"].asString();
                const auto productUrl = (*body)["productUrl"].asString();
                const auto gameId = (*body)["gameId"].asString();
                if ((store != "EpicGamesStore" &&
                     store != "NintendoEShop" &&
                     store != "PlayStationStore" &&
                     store != "MicrosoftStore" &&
                     store != "UbisoftStore" &&
                     store != "GOG" &&
                     store != "MetaQuestStore" &&
                     store != "EAApp" &&
                     store != "BattleNet" &&
                     store != "ItchIo" &&
                     store != "HumbleStore") ||
                    productUrl.empty() ||
                    !validCanonicalGameId(gameId)) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "invalid storefront catalog request"));
                    return;
                }
                const auto apply = (*body)["apply"].isBool() &&
                    (*body)["apply"].asBool();
                const auto acknowledgeReview =
                    (*body)["acknowledgeReview"].isBool() &&
                    (*body)["acknowledgeReview"].asBool();
                try {
                    Json::Value response;
                    response["game"] = runStorefrontCatalogImport(
                        store,
                        productUrl,
                        gameId,
                        apply,
                        acknowledgeReview);
                    response["applied"] = apply;
                    response["requiresApiRestart"] = false;
                    if (apply) {
                        catalog.reload(catalogPath());
                    }
                    callback(jsonResponse(response));
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/collection",
            [&catalogCollectionJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                callback(jsonResponse(catalogCollectionJob.json()));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/collection",
            [&catalogCollectionJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                const auto store = body && (*body)["store"].isString()
                    ? (*body)["store"].asString()
                    : std::string{"Steam"};
                const auto productId = body && (*body)["productId"].isString()
                    ? std::optional<std::string>{(*body)["productId"].asString()}
                    : std::nullopt;
                if (productId && (productId->empty() || productId->size() > 256)) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "invalid collection product id"));
                    return;
                }
                if (store != "Steam" && store != "Epic Games Store" &&
                    store != "Nintendo eShop" && store != "Google Play" &&
                    store != "Apple App Store" &&
                    store != "PlayStation Store" &&
                    store != "Microsoft Store" &&
                    store != "Ubisoft Store" && store != "GOG" &&
                    store != "Meta Quest Store" && store != "EA app" &&
                    store != "Battle.net" && store != "itch.io" &&
                    store != "Humble Store") {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "unsupported collection store"));
                    return;
                }
                if (store == "Epic Games Store") {
                    callback(jsonError(drogon::k400BadRequest,
                        "Epic Games Store는 구매 링크만 제공합니다. 자동 가격 수집은 중단되었습니다."));
                    return;
                }
                if (!catalogCollectionJob.start(store, productId)) {
                    callback(jsonError(
                        drogon::k409Conflict,
                        "collection is already running"));
                    return;
                }
                callback(jsonResponse(
                    catalogCollectionJob.json(),
                    drogon::k202Accepted));
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/mobile-sync",
            [&mobileCatalogSyncJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto store = request->getParameter("store");
                if (store != "GooglePlay" && store != "AppleAppStore" &&
                    store != "NintendoEShop" &&
                    store != "PlayStationStore" &&
                    store != "MicrosoftStore") {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "unsupported catalog discovery store"));
                    return;
                }
                try {
                    callback(jsonResponse(mobileCatalogSyncJob.status(store)));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/mobile-sync",
            [&mobileCatalogSyncJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                const auto store = body && (*body)["store"].isString()
                    ? (*body)["store"].asString()
                    : std::string{};
                const auto batchSize = body && (*body)["batchSize"].isInt()
                    ? (*body)["batchSize"].asInt()
                    : 10;
                if ((store != "GooglePlay" && store != "AppleAppStore" &&
                     store != "NintendoEShop" &&
                     store != "PlayStationStore" &&
                     store != "MicrosoftStore") ||
                    batchSize < 1 || batchSize > 100) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "valid store and batchSize are required"));
                    return;
                }
                if (!mobileCatalogSyncJob.start(store, batchSize)) {
                    callback(jsonError(
                        drogon::k409Conflict,
                        "mobile catalog synchronization is already running"));
                    return;
                }
                callback(jsonResponse(
                    mobileCatalogSyncJob.status(store),
                    drogon::k202Accepted));
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/mobile-sync/reviews/{1}",
            [&authService](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback,
               const std::string& productId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                const auto store = body && (*body)["store"].isString()
                    ? (*body)["store"].asString()
                    : std::string{};
                const auto resolution = body && (*body)["resolution"].isString()
                    ? (*body)["resolution"].asString()
                    : std::string{};
                if ((store != "GooglePlay" && store != "AppleAppStore" &&
                     store != "NintendoEShop" &&
                     store != "PlayStationStore" &&
                     store != "MicrosoftStore") ||
                    (resolution != "APPROVED" && resolution != "REJECTED")) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "valid store and resolution are required"));
                    return;
                }
                try {
                    callback(jsonResponse(resolveMobileCatalogReview(
                        store,
                        productId,
                        resolution)));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        error.what()));
                }
            },
            {drogon::Patch});
        drogon::app().registerHandler(
            "/api/admin/catalog/discovery",
            [&steamCatalogDiscoveryJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                callback(jsonResponse(steamCatalogDiscoveryJob.json()));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/discovery",
            [&steamCatalogDiscoveryJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                if (!steamCatalogDiscoveryJob.start()) {
                    callback(jsonError(
                        drogon::k409Conflict,
                        "Steam catalog discovery is already running"));
                    return;
                }
                callback(jsonResponse(
                    steamCatalogDiscoveryJob.json(),
                    drogon::k202Accepted));
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/sync",
            [&catalogSyncJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                callback(jsonResponse(catalogSyncJob.refresh()));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/sync",
            [&catalogSyncJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                const auto batchSize = body && (*body)["batchSize"].isInt()
                    ? (*body)["batchSize"].asInt()
                    : 20;
                if (batchSize < 1 || batchSize > 100) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "batchSize must be between 1 and 100"));
                    return;
                }
                if (!catalogSyncJob.start(batchSize)) {
                    callback(jsonError(
                        drogon::k409Conflict,
                        "catalog synchronization is already running"));
                    return;
                }
                callback(jsonResponse(
                    catalogSyncJob.json(),
                    drogon::k202Accepted));
            },
            {drogon::Post});
        drogon::app().registerHandler(
            "/api/admin/catalog/sync/reviews/{1}",
            [&catalogSyncJob, &authService](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                const std::string& appId) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                const auto body = request->getJsonObject();
                if (!validSteamAppId(appId) ||
                    !body ||
                    !(*body)["resolution"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "valid appId and resolution are required"));
                    return;
                }
                const auto resolution = (*body)["resolution"].asString();
                if (resolution != "APPROVED" && resolution != "REJECTED") {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "resolution must be APPROVED or REJECTED"));
                    return;
                }
                try {
                    if (!catalogSyncJob.resolve(appId, resolution)) {
                        callback(jsonError(
                            drogon::k409Conflict,
                            "catalog synchronization is running"));
                        return;
                    }
                    callback(jsonResponse(catalogSyncJob.json()));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        error.what()));
                }
            },
            {drogon::Patch});

        drogon::app().registerHandler(
            "/health",
            [](const drogon::HttpRequestPtr&,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                Json::Value json;
                json["status"] = "ok";
                callback(jsonResponse(json));
            },
            {drogon::Get});

        drogon::app().registerHandler(
            "/api/catalog-requests",
            [](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto body = request->getJsonObject();
                if (!body || !(*body)["query"].isString()) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "query is required"));
                    return;
                }
                const auto query = (*body)["query"].asString();
                if (query.size() < 2 || query.size() > 100) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "query must contain between 2 and 100 characters"));
                    return;
                }
                try {
                    callback(jsonResponse(
                        requestCatalogGame(query),
                        drogon::k202Accepted));
                } catch (const std::exception& error) {
                    callback(jsonError(
                        drogon::k500InternalServerError,
                        error.what()));
                }
            },
            {drogon::Post});

        drogon::app().registerHandler(
            "/api/games",
            [&queryService, &catalog](const drogon::HttpRequestPtr& request,
                            std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto query = request->getParameter("query");
                const auto store = request->getParameter("store");
                const auto platform = request->getParameter("platform");
                const auto genre = request->getParameter("genre");
                const auto tag = request->getParameter("tag");
                const auto sort = request->getParameter("sort");
                if (query.size() > 100 || genre.size() > 50 || tag.size() > 50) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "query, genre, or tag is too long"));
                    return;
                }
                GameCatalogFilter filter;
                std::size_t page = 1;
                std::size_t pageSize = 20;
                try {
                    filter.query = query;
                    filter.store = storeFromParameter(store);
                    filter.platform = platformFromParameter(platform);
                    filter.genre = genre;
                    filter.tag = tag;
                    page = unsignedParameter(
                        request->getParameter("page"), 1, 100000, "page");
                    pageSize = unsignedParameter(
                        request->getParameter("pageSize"), 20, 100, "pageSize");
                    if (!supportedGameSort(sort)) {
                        throw std::invalid_argument("unsupported game sort");
                    }
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                    return;
                }
                std::vector<CatalogGameSummary> summaries;
                auto catalogFilter = filter;
                // Runtime product compatibility (for example a Switch title
                // running on Switch 2) lives in the collected price data, not
                // necessarily in the canonical game's native platform list.
                // Let the price comparison apply the platform filter below.
                catalogFilter.platform.reset();
                const auto games = queryService.filterGames(catalogFilter);
                for (const auto& game : games) {
                    PriceComparisonCriteria criteria;
                    criteria.excludedStores = {Store::EpicGamesStore};
                    bool hasPurchaseLink = false;
                    for (const auto& linked : catalog.storeProducts(Store::EpicGamesStore)) {
                        if (linked.gameId == game.id && (!filter.store || *filter.store == linked.store) &&
                            (!filter.platform || std::find(linked.supportedPlatforms.begin(), linked.supportedPlatforms.end(),
                             *filter.platform) != linked.supportedPlatforms.end())) hasPurchaseLink = true;
                    }
                    criteria.platform = filter.platform;
                    criteria.includeForeignCurrencies = true;
                    const auto report = queryService.getGamePriceReportById(
                        game.id,
                        std::nullopt,
                        criteria);
                    if (!report || report->productReports.empty()) {
                        if ((filter.store || filter.platform) && !hasPurchaseLink) {
                            continue;
                        }
                        summaries.push_back(
                            CatalogGameSummary{
                                game,
                                std::nullopt,
                                std::nullopt,
                                {},
                                hasPurchaseLink ? "LinkOnly" : "Collecting"});
                        continue;
                    }
                    auto displayGame = game;
                    if (filter.platform &&
                        std::find(
                            displayGame.supportedPlatforms.begin(),
                            displayGame.supportedPlatforms.end(),
                            *filter.platform) ==
                            displayGame.supportedPlatforms.end()) {
                        displayGame.supportedPlatforms.push_back(*filter.platform);
                    }
                    std::optional<Money> lowestPrice;
                    std::optional<int> maxDiscountPercent;
                    std::string lastUpdatedAt;
                    bool hasMatchingProduct = hasPurchaseLink;
                    for (const auto& product : report->comparison.products) {
                        if (filter.store && product.store != *filter.store) {
                            continue;
                        }
                        hasMatchingProduct = true;
                        if (product.freshness != PriceFreshness::Fresh) {
                            continue;
                        }
                        const bool preferredCurrency =
                            product.currentPrice.currency == Currency::KRW;
                        const bool currentLowestIsPreferred = lowestPrice &&
                            lowestPrice->currency == Currency::KRW;
                        const bool comparable = lowestPrice &&
                            lowestPrice->currency == product.currentPrice.currency;
                        if (!lowestPrice ||
                            (preferredCurrency && !currentLowestIsPreferred) ||
                            (comparable &&
                             product.currentPrice.minorAmount <
                                 lowestPrice->minorAmount)) {
                            lowestPrice = product.currentPrice;
                        }
                        if (!maxDiscountPercent ||
                            product.discountPercent > *maxDiscountPercent) {
                            maxDiscountPercent = product.discountPercent;
                        }
                        if (product.lastSuccessfulCheckAt &&
                            *product.lastSuccessfulCheckAt > lastUpdatedAt) {
                            lastUpdatedAt = *product.lastSuccessfulCheckAt;
                        }
                    }
                    if (lowestPrice) {
                        summaries.push_back(CatalogGameSummary{
                            displayGame,
                            *lowestPrice,
                            maxDiscountPercent,
                            std::move(lastUpdatedAt),
                            "Available"});
                        continue;
                    }
                    if ((filter.store || filter.platform) && !hasMatchingProduct) {
                        continue;
                    }
                    summaries.push_back(CatalogGameSummary{
                        displayGame,
                        std::nullopt,
                        std::nullopt,
                        {},
                        filter.store && *filter.store == Store::EpicGamesStore && hasPurchaseLink
                            ? "LinkOnly" : "Stale"});
                }
                const auto selectedSort = sort.empty() ? "titleAsc" : sort;
                std::sort(summaries.begin(), summaries.end(), [&](const auto& left, const auto& right) {
                    return catalogSummaryLess(left, right, selectedSort);
                });
                Json::Value response;
                response["games"] = Json::arrayValue;
                response["page"] = Json::UInt64(page);
                response["pageSize"] = Json::UInt64(pageSize);
                response["total"] = Json::UInt64(summaries.size());
                const auto begin = std::min((page - 1) * pageSize, summaries.size());
                const auto end = std::min(begin + pageSize, summaries.size());
                for (auto index = begin; index < end; ++index) {
                    const auto& summary = summaries[index];
                    auto item = gameJson(summary.game);
                    item["priceStatus"] = summary.priceStatus;
                    if (summary.lowestPrice) {
                        item["lowestPrice"] = moneyJson(*summary.lowestPrice);
                    }
                    if (summary.maxDiscountPercent) {
                        item["maxDiscountPercent"] = *summary.maxDiscountPercent;
                    }
                    if (!summary.lastUpdatedAt.empty()) {
                        item["lastUpdatedAt"] = summary.lastUpdatedAt;
                    }
                    response["games"].append(std::move(item));
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        drogon::app().registerHandler(
            "/api/catalog/filters",
            [&catalog](const drogon::HttpRequestPtr&,
                       std::function<void(const HttpResponsePtr&)>&& callback) {
                const std::vector<Store> supportedStores{
                    Store::Steam,
                    Store::EpicGamesStore,
                    Store::NintendoEShop,
                    Store::PlayStationStore,
                    Store::MicrosoftStore,
                    Store::GooglePlay,
                    Store::AppleAppStore,
                    Store::UbisoftStore,
                    Store::GOG,
                    Store::MetaQuestStore,
                    Store::EAApp,
                    Store::BattleNet,
                    Store::ItchIo,
                    Store::HumbleStore};
                const std::vector<Platform> supportedPlatforms{
                    Platform::Windows,
                    Platform::MacOS,
                    Platform::Linux,
                    Platform::Android,
                    Platform::IOS,
                    Platform::IPadOS,
                    Platform::NintendoSwitch,
                    Platform::NintendoSwitch2,
                    Platform::PlayStation4,
                    Platform::PlayStation5,
                    Platform::XboxOne,
                    Platform::XboxSeries,
                    Platform::MetaQuest};
                std::set<std::string> genres;
                std::set<std::string> tags;
                Json::Value response;
                response["stores"] = Json::arrayValue;
                for (const auto store : supportedStores) {
                    if (!catalog.storeProducts(store).empty()) {
                        response["stores"].append(toString(store));
                    }
                }
                for (const auto& game : catalog.allGames()) {
                    genres.insert(game.genres.begin(), game.genres.end());
                    tags.insert(game.tags.begin(), game.tags.end());
                }
                response["platforms"] = Json::arrayValue;
                response["genres"] = Json::arrayValue;
                response["tags"] = Json::arrayValue;
                for (const auto platform : supportedPlatforms) {
                    response["platforms"].append(toString(platform));
                }
                for (const auto& genre : genres) {
                    response["genres"].append(genre);
                }
                for (const auto& tag : tags) {
                    response["tags"].append(tag);
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        drogon::app().registerHandler(
            "/api/games/{1}/prices",
            [&queryService, &database, &catalog](const drogon::HttpRequestPtr& request,
                            std::function<void(const HttpResponsePtr&)>&& callback,
                            const std::string& gameId) {
                PriceComparisonCriteria criteria;
                try {
                    criteria = comparisonCriteria(request);
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                    return;
                }
                const auto report = queryService.getGamePriceReportById(
                    gameId, std::nullopt, criteria);
                if (!report) {
                    callback(jsonError(drogon::k404NotFound, "game not found"));
                    return;
                }
                Json::Value response;
                response["game"] = gameJson(report->comparison.game);
                response["products"] = Json::arrayValue;
                response["purchaseLinks"] = Json::arrayValue;
                for (const auto& linked : catalog.storeProducts(Store::EpicGamesStore)) {
                    if (linked.gameId != gameId) continue;
                    if (linked.region != criteria.region || linked.edition != criteria.edition ||
                        linked.offerType != criteria.offerType) continue;
                    if (criteria.platform && std::find(linked.supportedPlatforms.begin(),
                        linked.supportedPlatforms.end(), *criteria.platform) == linked.supportedPlatforms.end()) continue;
                    Json::Value item;
                    item["store"] = toString(linked.store);
                    item["productId"] = linked.productId;
                    item["purchaseUrl"] = linked.productUrl;
                    item["notice"] = "자동 가격 수집이 지원되지 않습니다. 최신 가격은 공식 Store에서 확인하세요.";
                    response["purchaseLinks"].append(item);
                }
                for (const auto& productReport : report->productReports) {
                    std::optional<Money> effectivePrice;
                    const auto& product = productReport.product;
                    std::optional<Money> standaloneReferencePrice;
                    for (const auto& candidate : report->productReports) {
                        const auto& base = candidate.product;
                        if (base.offerType != OfferType::BaseGame) continue;
                        const Money reference = base.regularPrice.value_or(base.currentPrice);
                        if (reference.currency == product.currentPrice.currency &&
                            (!standaloneReferencePrice ||
                             reference.minorAmount > standaloneReferencePrice->minorAmount)) {
                            standaloneReferencePrice = reference;
                        }
                    }
                    if (product.offerType == OfferType::Bundle && product.regularPrice &&
                        standaloneReferencePrice && product.regularPrice->minorAmount > 0 &&
                        standaloneReferencePrice->minorAmount <= product.regularPrice->minorAmount) {
                        effectivePrice = Money{
                            static_cast<std::int64_t>(std::llround(
                                static_cast<double>(product.currentPrice.minorAmount) *
                                standaloneReferencePrice->minorAmount /
                                product.regularPrice->minorAmount)),
                            product.currentPrice.currency};
                    }
                    response["products"].append(
                        productJson(productReport, &database, effectivePrice));
                }
                if (report->comparison.cheapestProduct) {
                    response["cheapest"]["productId"] =
                        report->comparison.cheapestProduct->productId;
                    response["cheapest"]["store"] =
                        toString(report->comparison.cheapestProduct->store);
                    response["cheapest"]["price"] =
                        moneyJson(report->comparison.cheapestProduct->currentPrice);
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        drogon::app().registerHandler(
            "/api/games/{1}/price-history",
            [&queryService, &database](const drogon::HttpRequestPtr& request,
                            std::function<void(const HttpResponsePtr&)>&& callback,
                            const std::string& gameId) {
                const auto since = request->getParameter("since");
                if (!since.empty() && !isIsoDate(since)) {
                    callback(jsonError(
                        drogon::k400BadRequest, "since must use YYYY-MM-DD"));
                    return;
                }
                PriceComparisonCriteria criteria;
                try{criteria=comparisonCriteria(request);}catch(const std::invalid_argument& error){callback(jsonError(drogon::k400BadRequest,error.what()));return;}
                const auto report = queryService.getGamePriceHistoryById(
                    gameId,
                    since.empty() ? std::nullopt
                                  : std::optional<std::string>{since},criteria);
                if (!report) {
                    callback(jsonError(drogon::k404NotFound, "game not found"));
                    return;
                }

                Json::Value response;
                response["game"] = gameJson(report->game);
                response["histories"] = Json::arrayValue;
                for (const auto& productHistory : report->productHistories) {
                    Json::Value history;
                    history["productId"] = productHistory.product.productId;
                    history["store"] = toString(productHistory.product.store);
                    history["offerType"] = toString(productHistory.product.offerType);
                    if (!productHistory.offerName.empty()) {
                        history["offerName"] = productHistory.offerName;
                    }
                    history["observations"] = Json::arrayValue;
                    for (const auto& observation : productHistory.observations) {
                        Json::Value item;
                        item["price"] = moneyJson(observation.price);
                        if (observation.regularPrice) {
                            item["regularPrice"] = moneyJson(*observation.regularPrice);
                        }
                        item["discountPercent"] = observation.discountPercent;
                        item["purchasable"] = observation.purchasable;
                        item["observedAt"] = observation.observedAt;
                        if (const auto converted = convertedKrwJson(
                                database, observation.price,
                                observation.observedAt)) {
                            item["krwConversion"] = *converted;
                        }
                        history["observations"].append(std::move(item));
                    }
                    response["histories"].append(std::move(history));
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        drogon::app().registerHandler(
            "/api/collection-runs",
            [&queryService, &authService](const drogon::HttpRequestPtr& request,
                            std::function<void(const HttpResponsePtr&)>&& callback) {
                if (const auto error = adminAccessError(request, authService)) {
                    callback(error);
                    return;
                }
                std::size_t limit = 20;
                const auto requestedLimit = request->getParameter("limit");
                if (!requestedLimit.empty()) {
                    if (!std::all_of(
                            requestedLimit.begin(), requestedLimit.end(),
                            [](unsigned char character) { return std::isdigit(character); })) {
                        callback(jsonError(
                            drogon::k400BadRequest,
                            "limit must be an integer between 1 and 100"));
                        return;
                    }
                    try {
                        limit = static_cast<std::size_t>(std::stoul(requestedLimit));
                    } catch (const std::exception&) {
                        limit = 0;
                    }
                    if (limit < 1 || limit > 100) {
                        callback(jsonError(
                            drogon::k400BadRequest,
                            "limit must be an integer between 1 and 100"));
                        return;
                    }
                }

                const auto runs = queryService.getCollectionRuns();
                Json::Value response;
                response["runs"] = Json::arrayValue;
                std::size_t added = 0;
                for (auto run = runs.rbegin(); run != runs.rend() && added < limit;
                     ++run, ++added) {
                    Json::Value item;
                    item["id"] = Json::Int64(run->id);
                    item["store"] = toString(run->store);
                    item["status"] = toString(run->status);
                    item["productsFound"] = Json::UInt64(run->productsFound);
                    item["productsRejected"] = Json::UInt64(run->productsRejected);
                    item["productsFailed"] = Json::UInt64(run->productsFailed);
                    item["retryCount"] = Json::UInt64(run->retryCount);
                    item["startedAt"] = run->startedAt;
                    if (!run->gameId.empty()) {
                        item["gameId"] = run->gameId;
                    }
                    if (!run->finishedAt.empty()) item["finishedAt"] = run->finishedAt;
                    if (!run->errorMessage.empty()) {
                        item["errorMessage"] = run->errorMessage;
                    }
                    response["runs"].append(std::move(item));
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        const auto host = serverHost();
        const int port = serverPort();
        std::cout << "Game Price API listening on http://" << host << ':' << port << '\n';
        drogon::app().addListener(host, port).run();
    } catch (const std::exception& error) {
        std::cerr << "API error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
