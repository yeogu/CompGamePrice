#include "game_price/app/game_query_service.h"
#include "game_price/domain/domain_types.h"
#include "game_price/persistence/database.h"
#include "game_price/persistence/store_product_repository.h"

#include <drogon/drogon.h>

#include <cstdlib>
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

}  // namespace

int main() {
    using namespace game_price;

    try {
        Database database(GAME_PRICE_DATABASE_PATH);
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

        const int port = serverPort();
        std::cout << "Game Price API listening on http://127.0.0.1:" << port << '\n';
        drogon::app().addListener("127.0.0.1", port).run();
    } catch (const std::exception& error) {
        std::cerr << "API error: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
