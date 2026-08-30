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

#include <cstdlib>
#include <algorithm>
#include <cctype>
#include <iostream>
#include <filesystem>
#include <fstream>
#include <regex>
#include <set>
#include <sstream>
#include <iterator>
#include <mutex>
#include <thread>
#include <stdexcept>
#include <string>
#include <map>

namespace {

using namespace game_price;
using drogon::HttpResponse;
using drogon::HttpResponsePtr;

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
    return json;
}

Json::Value productJson(const ProductPriceReport& report) {
    Json::Value json;
    json["productId"] = report.product.productId;
    json["store"] = toString(report.product.store);
    json["purchaseUrl"] = report.purchaseUrl;
    json["region"] = toString(report.product.region);
    json["edition"] = toString(report.product.edition);
    json["offerType"] = toString(report.product.offerType);
    json["price"] = moneyJson(report.product.currentPrice);
    if (report.product.regularPrice) {
        json["regularPrice"] = moneyJson(*report.product.regularPrice);
    }
    json["discountPercent"] = report.product.discountPercent;
    json["purchasable"] = report.product.purchasable;
    if (report.product.lastCheckedAt) {
        json["lastCheckedAt"] = *report.product.lastCheckedAt;
    }
    if (report.product.lastSuccessfulCheckAt) {
        json["lastSuccessfulCheckAt"] =
            *report.product.lastSuccessfulCheckAt;
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

int serverPort() {
    const char* value = std::getenv("GAME_PRICE_API_PORT");
    return value ? std::stoi(value) : 8080;
}

std::string databasePath() {
    const char* value = std::getenv("GAME_PRICE_DATABASE_PATH");
    return value ? value : GAME_PRICE_DATABASE_PATH;
}

bool catalogAdminEnabled() {
    const char* value = std::getenv("CATALOG_ADMIN_ENABLED");
    return value && std::string(value) == "true";
}

bool isLoopbackRequest(const drogon::HttpRequestPtr& request) {
    const auto address = request->peerAddr().toIp();
    return address == "127.0.0.1" || address == "::1";
}

bool validSteamAppId(const std::string& value) {
    return !value.empty() &&
        std::all_of(value.begin(), value.end(), [](unsigned char character) {
            return std::isdigit(character) != 0;
        });
}

bool validCanonicalGameId(const std::string& value) {
    static const std::regex pattern{"[a-z0-9]+(?:-[a-z0-9]+)*"};
    return value.empty() || std::regex_match(value, pattern);
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

Json::Value runCatalogImport(
    const std::string& appId,
    const std::string& gameId,
    bool apply) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto temporary = std::filesystem::temp_directory_path() /
        ("compgameprice-catalog-" + appId + ".json");
    const auto script = std::filesystem::path(PROJECT_SOURCE_DIR) /
        "tools/add_steam_catalog_game.py";
    const auto catalog = std::filesystem::path(SAMPLE_DATA_DIR) /
        "game_catalog.json";
    std::string command = "python3 " + shellQuoted(script.string()) +
        " --app-id " + appId +
        " --catalog " + shellQuoted(catalog.string());
    if (!gameId.empty()) {
        command += " --game-id " + gameId;
    }
    if (apply) {
        command += " --apply";
    }
    command += " > " + shellQuoted(temporary.string());
    command += " 2>&1";
    const auto exitCode = std::system(command.c_str());
    std::ifstream input(temporary);
    const std::string output{
        std::istreambuf_iterator<char>{input},
        std::istreambuf_iterator<char>{}};
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    if (exitCode != 0) {
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

Json::Value runStoreSearch(const std::string& store, const std::string& query) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    if (store != "Steam") {
        throw std::invalid_argument("store is not supported yet");
    }
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-store-search.json";
    const auto script = std::filesystem::path(PROJECT_SOURCE_DIR) /
        "tools/search_steam_catalog.py";
    const auto command = "python3 " + shellQuoted(script.string()) +
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

class CatalogCollectionJob {
public:
    bool start() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (status_ == "RUNNING") {
            return false;
        }
        ++id_;
        status_ = "RUNNING";
        error_.clear();
        std::thread([this]() { run(); }).detach();
        return true;
    }

    Json::Value json() const {
        std::lock_guard<std::mutex> lock(mutex_);
        Json::Value result;
        result["id"] = Json::UInt64(id_);
        result["status"] = status_;
        if (!error_.empty()) {
            result["error"] = error_;
        }
        return result;
    }

private:
    void run() {
        const auto project = std::filesystem::path(PROJECT_SOURCE_DIR);
        const auto command = "python3 " + shellQuoted(
            (project / "tools/run_steam_pipeline.py").string()) +
            " --tracker " + shellQuoted(
                (project / "build/game_price_tracker").string()) +
            " --catalog " + shellQuoted(
                (project / "data/game_catalog.json").string()) +
            " --output-dir " + shellQuoted(
                (project / "snapshots/latest").string());
        const auto exitCode = std::system(command.c_str());
        std::lock_guard<std::mutex> lock(mutex_);
        status_ = exitCode == 0 ? "SUCCEEDED" : "FAILED";
        if (exitCode != 0) {
            error_ = "Steam collection pipeline failed";
        }
    }

    mutable std::mutex mutex_;
    std::uint64_t id_{};
    std::string status_{"IDLE"};
    std::string error_;
};

Json::Value runCatalogSyncCommand(
    const std::filesystem::path& script,
    const std::string& arguments) {
    std::lock_guard<std::mutex> toolLock(catalogToolMutex());
    const auto project = std::filesystem::path(PROJECT_SOURCE_DIR);
    const auto temporary = std::filesystem::temp_directory_path() /
        "compgameprice-catalog-sync.json";
    std::string command = "python3 " + shellQuoted(script.string()) +
        " --catalog " + shellQuoted(
            (project / "data/game_catalog.json").string()) +
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
    if (exitCode != 0 || !parsed) {
        throw std::runtime_error("Steam catalog synchronization failed");
    }
    return result;
}

Json::Value runCatalogSyncTool(bool synchronize, int batchSize) {
    const auto project = std::filesystem::path(PROJECT_SOURCE_DIR);
    if (synchronize) {
        return runCatalogSyncCommand(
            project / "tools/run_catalog_sync_pipeline.py",
            " --tracker " + shellQuoted(
                (project / "build/game_price_tracker").string()) +
            " --output-dir " + shellQuoted(
                (project / "snapshots/latest").string()) +
            " --batch-size " + std::to_string(batchSize));
    }
    return runCatalogSyncCommand(
        project / "tools/sync_steam_catalog.py",
        " --status");
}

void resolveCatalogReview(
    const std::string& appId,
    const std::string& resolution) {
    const auto project = std::filesystem::path(PROJECT_SOURCE_DIR);
    runCatalogSyncCommand(
        project / "tools/sync_steam_catalog.py",
        " --resolve-app-id " + appId +
        " --resolution " + resolution);
}

Json::Value requestCatalogGame(const std::string& query) {
    const auto project = std::filesystem::path(PROJECT_SOURCE_DIR);
    return runCatalogSyncCommand(
        project / "tools/sync_steam_catalog.py",
        " --request-game " + shellQuoted(query));
}

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
            catalog_.reload(
                std::string(SAMPLE_DATA_DIR) + "/game_catalog.json");
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
std::string env(const char* name) { const char* value=std::getenv(name); return value?value:""; }
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
    if (value == "Google Play") {
        return Store::GooglePlay;
    }
    if (value == "Apple App Store") {
        return Store::AppleAppStore;
    }
    throw std::invalid_argument("unsupported store");
}

PriceComparisonCriteria comparisonCriteria(
    const drogon::HttpRequestPtr& request) {
    PriceComparisonCriteria criteria;
    const auto region = request->getParameter("region");
    const auto edition = request->getParameter("edition");
    const auto offerType = request->getParameter("offerType");
    const auto currency = request->getParameter("currency");
    const auto platform = request->getParameter("platform");

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
    if (!currency.empty() && currency != "KRW") {
        throw std::invalid_argument("currency must be KRW");
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

Json::Value authJson(const AuthResult& result) {
    Json::Value json;
    json["user"]["id"] = Json::Int64(result.user.id);
    json["user"]["email"] = result.user.email;
    json["token"] = result.token;
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
        Database database(databasePath());
        StoreProductRepository repository(database);
        repository.initializeSchema();
        GameCatalog catalog(std::string(SAMPLE_DATA_DIR) + "/game_catalog.json");
        GameQueryService queryService(catalog, repository);
        AccountRepository accountRepository(database);
        AuthService authService(accountRepository);
        OAuthService oauthService(accountRepository);
        CatalogCollectionJob catalogCollectionJob;
        CatalogSyncJob catalogSyncJob(catalog);

        drogon::app().registerPreRoutingAdvice(
            [](const drogon::HttpRequestPtr& request,
               drogon::AdviceCallback&& callback,
               drogon::AdviceChainCallback&& next) {
                if (request->method() == drogon::Options) {
                    callback(jsonResponse(Json::Value{}));
                    return;
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
                if (!user) { callback(jsonError(drogon::k401Unauthorized, "authentication required")); return; }
                Json::Value json; json["id"] = Json::Int64(user->id); json["email"] = user->email;
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
                        const auto value=(*body)["platform"].asString();
                        if(value=="Windows")platform=Platform::Windows;else if(value=="macOS")platform=Platform::MacOS;else if(value=="Linux")platform=Platform::Linux;else if(value=="Android")platform=Platform::Android;else if(value=="iOS")platform=Platform::IOS;else if(value=="iPadOS")platform=Platform::IPadOS;else if(value=="Nintendo Switch")platform=Platform::NintendoSwitch;else if(value=="Nintendo Switch 2")platform=Platform::NintendoSwitch2;else{callback(jsonError(drogon::k400BadRequest,"unsupported platform"));return;}
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
            [](const drogon::HttpRequestPtr&,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                Json::Value response;
                response["enabled"] = catalogAdminEnabled();
                callback(jsonResponse(response));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/steam",
            [&catalog](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                if (!catalogAdminEnabled() || !isLoopbackRequest(request)) {
                    callback(jsonError(
                        drogon::k403Forbidden,
                        "catalog admin is disabled"));
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
                        catalog.reload(
                            std::string(SAMPLE_DATA_DIR) + "/game_catalog.json");
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
            [](const drogon::HttpRequestPtr& request,
               std::function<void(const HttpResponsePtr&)>&& callback) {
                if (!catalogAdminEnabled() || !isLoopbackRequest(request)) {
                    callback(jsonError(
                        drogon::k403Forbidden,
                        "catalog admin is disabled"));
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
            "/api/admin/catalog/collection",
            [&catalogCollectionJob](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (!catalogAdminEnabled() || !isLoopbackRequest(request)) {
                    callback(jsonError(
                        drogon::k403Forbidden,
                        "catalog admin is disabled"));
                    return;
                }
                callback(jsonResponse(catalogCollectionJob.json()));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/collection",
            [&catalogCollectionJob](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (!catalogAdminEnabled() || !isLoopbackRequest(request)) {
                    callback(jsonError(
                        drogon::k403Forbidden,
                        "catalog admin is disabled"));
                    return;
                }
                if (!catalogCollectionJob.start()) {
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
            "/api/admin/catalog/sync",
            [&catalogSyncJob](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (!catalogAdminEnabled() || !isLoopbackRequest(request)) {
                    callback(jsonError(
                        drogon::k403Forbidden,
                        "catalog admin is disabled"));
                    return;
                }
                callback(jsonResponse(catalogSyncJob.refresh()));
            },
            {drogon::Get});
        drogon::app().registerHandler(
            "/api/admin/catalog/sync",
            [&catalogSyncJob](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback) {
                if (!catalogAdminEnabled() || !isLoopbackRequest(request)) {
                    callback(jsonError(
                        drogon::k403Forbidden,
                        "catalog admin is disabled"));
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
            [&catalogSyncJob](
                const drogon::HttpRequestPtr& request,
                std::function<void(const HttpResponsePtr&)>&& callback,
                const std::string& appId) {
                if (!catalogAdminEnabled() || !isLoopbackRequest(request)) {
                    callback(jsonError(
                        drogon::k403Forbidden,
                        "catalog admin is disabled"));
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
            [&queryService](const drogon::HttpRequestPtr& request,
                            std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto query = request->getParameter("query");
                const auto store = request->getParameter("store");
                const auto platform = request->getParameter("platform");
                const auto genre = request->getParameter("genre");
                const auto tag = request->getParameter("tag");
                if (query.size() > 100 || genre.size() > 50 || tag.size() > 50) {
                    callback(jsonError(
                        drogon::k400BadRequest,
                        "query, genre, or tag is too long"));
                    return;
                }
                GameCatalogFilter filter;
                try {
                    filter.query = query;
                    filter.store = storeFromParameter(store);
                    filter.platform = platformFromParameter(platform);
                    filter.genre = genre;
                    filter.tag = tag;
                } catch (const std::invalid_argument& error) {
                    callback(jsonError(drogon::k400BadRequest, error.what()));
                    return;
                }
                Json::Value response;
                response["games"] = Json::arrayValue;
                const auto games = queryService.filterGames(filter);
                for (const auto& game : games) {
                    auto item = gameJson(game);
                    const auto report = queryService.getGamePriceReportById(game.id);
                    if (!report || report->productReports.empty()) {
                        item["priceStatus"] = "Collecting";
                    } else if (report->comparison.cheapestProduct) {
                        item["priceStatus"] = "Available";
                        item["lowestPrice"] = moneyJson(
                            report->comparison.cheapestProduct->currentPrice);
                    } else {
                        item["priceStatus"] = "Stale";
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
                    Store::GooglePlay,
                    Store::AppleAppStore};
                std::set<std::string> platforms;
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
                    for (const auto platform : game.supportedPlatforms) {
                        platforms.insert(toString(platform));
                    }
                    genres.insert(game.genres.begin(), game.genres.end());
                    tags.insert(game.tags.begin(), game.tags.end());
                }
                response["platforms"] = Json::arrayValue;
                response["genres"] = Json::arrayValue;
                response["tags"] = Json::arrayValue;
                for (const auto& platform : platforms) {
                    response["platforms"].append(platform);
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
            [&queryService](const drogon::HttpRequestPtr& request,
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
                for (const auto& productReport : report->productReports) {
                    response["products"].append(productJson(productReport));
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
            [&queryService](const drogon::HttpRequestPtr& request,
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
                        history["observations"].append(std::move(item));
                    }
                    response["histories"].append(std::move(history));
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        drogon::app().registerHandler(
            "/api/collection-runs",
            [&queryService](const drogon::HttpRequestPtr& request,
                            std::function<void(const HttpResponsePtr&)>&& callback) {
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
                    if (!run->finishedAt.empty()) item["finishedAt"] = run->finishedAt;
                    if (!run->errorMessage.empty()) {
                        item["errorMessage"] = run->errorMessage;
                    }
                    response["runs"].append(std::move(item));
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        const int port = serverPort();
        std::cout << "Game Price API listening on http://127.0.0.1:" << port << '\n';
        drogon::app().addListener("127.0.0.1", port).run();
    } catch (const std::exception& error) {
        std::cerr << "API error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
