#include "game_price/app/game_query_service.h"
#include "game_price/domain/domain_types.h"
#include "game_price/persistence/database.h"
#include "game_price/persistence/store_product_repository.h"
#include "game_price/support/date_utils.h"

#include <drogon/drogon.h>

#include <cstdlib>
#include <algorithm>
#include <cctype>
#include <iostream>
#include <string>

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

Json::Value productJson(const ProductPriceReport& report) {
    Json::Value json;
    json["productId"] = report.product.productId;
    json["store"] = toString(report.product.store);
    json["price"] = moneyJson(report.product.currentPrice);
    if (report.product.regularPrice) {
        json["regularPrice"] = moneyJson(*report.product.regularPrice);
    }
    json["discountPercent"] = report.product.discountPercent;
    json["purchasable"] = report.product.purchasable;
    for (const auto platform : report.product.supportedPlatforms) {
        json["platforms"].append(toString(platform));
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
    response->addHeader("Access-Control-Allow-Origin", "*");
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

}  // namespace

int main() {
    using namespace game_price;

    try {
        Database database(databasePath());
        StoreProductRepository repository(database);
        repository.initializeSchema();
        GameCatalog catalog(std::string(SAMPLE_DATA_DIR) + "/games.txt");
        GameQueryService queryService(catalog, repository);

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
            "/api/games",
            [&queryService](const drogon::HttpRequestPtr& request,
                            std::function<void(const HttpResponsePtr&)>&& callback) {
                const auto query = request->getParameter("query");
                if (query.empty()) {
                    callback(jsonError(
                        drogon::k400BadRequest, "query parameter is required"));
                    return;
                }
                Json::Value response;
                response["games"] = Json::arrayValue;
                for (const auto& game : queryService.searchGames(query)) {
                    Json::Value item;
                    item["id"] = game.id;
                    item["title"] = game.title;
                    response["games"].append(std::move(item));
                }
                callback(jsonResponse(response));
            },
            {drogon::Get});

        drogon::app().registerHandler(
            "/api/games/{1}/prices",
            [&queryService](const drogon::HttpRequestPtr&,
                            std::function<void(const HttpResponsePtr&)>&& callback,
                            const std::string& gameId) {
                const auto report = queryService.getGamePriceReportById(gameId);
                if (!report) {
                    callback(jsonError(drogon::k404NotFound, "game not found"));
                    return;
                }
                Json::Value response;
                response["game"]["id"] = report->comparison.game.id;
                response["game"]["title"] = report->comparison.game.title;
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
                const auto report = queryService.getGamePriceHistoryById(
                    gameId,
                    since.empty() ? std::nullopt
                                  : std::optional<std::string>{since});
                if (!report) {
                    callback(jsonError(drogon::k404NotFound, "game not found"));
                    return;
                }

                Json::Value response;
                response["game"]["id"] = report->game.id;
                response["game"]["title"] = report->game.title;
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
