#include "game_price/app/command_line.h"
#include "game_price/app/game_query_service.h"
#include "game_price/catalog/game_catalog.h"
#include "game_price/collection/apple_app_store_provider.h"
#include "game_price/collection/collection_service.h"
#include "game_price/collection/epic_games_provider.h"
#include "game_price/collection/google_play_provider.h"
#include "game_price/collection/nintendo_eshop_provider.h"
#include "game_price/collection/steam_provider.h"
#include "game_price/persistence/database.h"
#include "game_price/persistence/store_product_repository.h"
#include "game_price/notification/account_repository.h"
#include "game_price/notification/alert_service.h"
#include "game_price/pricing/price_comparison_service.h"
#include "game_price/pricing/price_history_service.h"
#include "game_price/recommendation/purchase_recommendation_service.h"

#include <algorithm>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace game_price;

std::string catalogPath() {
    const char* value = std::getenv("GAME_PRICE_CATALOG_PATH");
    return value ? value : std::string(SAMPLE_DATA_DIR) + "/game_catalog.json";
}

CollectionResult collectStoreProducts(
    const GameCatalog& catalog,
    const Game& game,
    StoreProductRepository& repository,
    const std::string& dataDirectory) {
    SteamProvider steam(dataDirectory + "/steam_products.txt");
    EpicGamesProvider epicGames(dataDirectory + "/epic_games_products.txt");
    GooglePlayProvider googlePlay(dataDirectory + "/google_play_products.txt");
    AppleAppStoreProvider appleAppStore(dataDirectory + "/apple_app_store_products.csv");
    NintendoEShopProvider nintendo(dataDirectory + "/nintendo_eshop_products.csv");
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{
        steam, epicGames, googlePlay, appleAppStore, nintendo};

    AccountRepository accounts(repository.database());
    AlertService alerts(accounts);
    CollectionService service(catalog, repository, std::move(providers), 2, &alerts);
    const auto result = service.collect(game);
    std::cout << "Collection runs:\n";
    for (const auto& run : result.runs) {
        std::cout << "- " << toString(run.store) << ": " << toString(run.status)
                  << ", attempt=" << run.attemptNumber
                  << ", products=" << run.productsFound
                  << ", rejected=" << run.productsRejected
                  << ", failed=" << run.productsFailed;
        if (!run.errorMessage.empty()) std::cout << ", error=" << run.errorMessage;
        std::cout << '\n';
    }
    std::cout << "Saved " << result.totalProducts
              << " normalized products to SQLite.\n";
    return result;
}

CollectionResult collectSteamProduct(
    const GameCatalog& catalog,
    const Game& game,
    StoreProductRepository& repository,
    const std::string& dataDirectory) {
    SteamProvider steam(dataDirectory + "/steam_products.txt");
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{steam};
    AccountRepository accounts(repository.database());
    AlertService alerts(accounts);
    CollectionService service(catalog, repository, std::move(providers), 2, &alerts);
    const auto result = service.collect(game);
    std::cout << "Steam collection runs:\n";
    for (const auto& run : result.runs) {
        std::cout << "- " << toString(run.store) << ": " << toString(run.status)
                  << ", attempt=" << run.attemptNumber
                  << ", products=" << run.productsFound
                  << ", rejected=" << run.productsRejected
                  << ", failed=" << run.productsFailed;
        if (!run.errorMessage.empty()) std::cout << ", error=" << run.errorMessage;
        std::cout << '\n';
    }
    std::cout << "Saved " << result.totalProducts
              << " normalized Steam products to SQLite.\n";
    return result;
}

CollectionResult collectAllSteamProducts(
    const GameCatalog& catalog,
    StoreProductRepository& repository,
    const std::string& dataDirectory) {
    SteamProvider steam(dataDirectory + "/steam_products.txt");
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{steam};
    AccountRepository accounts(repository.database());
    AlertService alerts(accounts);
    CollectionService service(catalog, repository, std::move(providers), 2, &alerts);

    CollectionResult combined;
    for (const auto& game : catalog.allGames()) {
        const auto result = service.collect(game);
        combined.runs.insert(
            combined.runs.end(), result.runs.begin(), result.runs.end());
        combined.totalProducts += result.totalProducts;
        std::cout << "- " << game.title << ": " << result.totalProducts
                  << " Steam product(s) saved\n";
    }
    return combined;
}

CollectionResult collectAllAppleProducts(
    const GameCatalog& catalog,
    StoreProductRepository& repository,
    const std::string& dataDirectory) {
    AppleAppStoreProvider apple(
        dataDirectory + "/apple_app_store_products.csv");
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{
        apple};
    AccountRepository accounts(repository.database());
    AlertService alerts(accounts);
    CollectionService service(
        catalog,
        repository,
        std::move(providers),
        2,
        &alerts);

    CollectionResult combined;
    for (const auto& game : catalog.allGames()) {
        const auto result = service.collect(game);
        combined.runs.insert(
            combined.runs.end(),
            result.runs.begin(),
            result.runs.end());
        combined.totalProducts += result.totalProducts;
        std::cout << "- " << game.title << ": " << result.totalProducts
                  << " Apple product(s) saved\n";
    }
    return combined;
}

bool collectionCompletedSuccessfully(const CollectionResult& result) {
    std::vector<std::pair<Store, CrawlRunStatus>> finalStatuses;
    for (const auto& run : result.runs) {
        const auto existing = std::find_if(
            finalStatuses.begin(), finalStatuses.end(),
            [&run](const auto& entry) { return entry.first == run.store; });
        if (existing == finalStatuses.end()) {
            finalStatuses.emplace_back(run.store, run.status);
        } else {
            existing->second = run.status;
        }
    }
    return !finalStatuses.empty() && std::all_of(
        finalStatuses.begin(), finalStatuses.end(),
        [](const auto& entry) { return entry.second == CrawlRunStatus::Succeeded; });
}

bool printCollectionRuns(const GameQueryService& queryService) {
    const auto runs = queryService.getCollectionRuns();
    if (runs.empty()) {
        std::cout << "No collection runs found.\n";
        return false;
    }

    std::cout << "Collection run history:\n";
    for (const auto& run : runs) {
        std::cout << "- #" << run.id << ' ' << toString(run.store)
                  << ": " << toString(run.status)
                  << ", products=" << run.productsFound
                  << ", rejected=" << run.productsRejected
                  << ", failed=" << run.productsFailed
                  << ", retries=" << run.retryCount
                  << ", started=" << run.startedAt;
        if (!run.finishedAt.empty()) std::cout << ", finished=" << run.finishedAt;
        if (!run.errorMessage.empty()) std::cout << ", error=" << run.errorMessage;
        std::cout << '\n';
    }
    return true;
}

std::optional<PriceComparisonResult> printPriceComparison(
    const std::optional<GamePriceReport>& report) {
    if (!report) return std::nullopt;
    const auto& result = report->comparison;

    std::cout << result.game.title << " prices:\n";
    for (const auto& product : result.products) {
        std::cout << "- " << toString(product.store) << ": "
                  << product.currentPrice.minorAmount << ' '
                  << toString(product.currentPrice.currency) << '\n';
    }

    if (result.cheapestProduct) {
        std::cout << "Cheapest: " << toString(result.cheapestProduct->store)
                  << " - " << result.cheapestProduct->currentPrice.minorAmount
                  << ' ' << toString(result.cheapestProduct->currentPrice.currency) << '\n';
    } else {
        std::cout << "No purchasable product found in SQLite.\n";
    }
    return result;
}

bool printPriceHistory(
    const GamePriceReport& report) {
    bool foundHistory = false;
    std::cout << "Price history summary:\n";
    for (const auto& productReport : report.productReports) {
        if (!productReport.history || !productReport.recommendation) continue;
        const auto& summary = *productReport.history;
        const auto& recommendation = *productReport.recommendation;
        foundHistory = true;
        std::cout << "- " << toString(summary.store)
                  << ": current=" << summary.currentPrice.minorAmount
                  << ", low=" << summary.lowestPrice.minorAmount
                  << ", high=" << summary.highestPrice.minorAmount
                  << ", average=" << summary.averagePrice.minorAmount
                  << ' ' << toString(summary.currentPrice.currency)
                  << ", trend=" << toString(summary.trend)
                  << ", observations=" << summary.observationCount << '\n';

        std::cout << "  Recommendation: "
                  << toString(recommendation.recommendation) << '\n';
        std::cout << "  Price metrics: "
                  << recommendation.amountAboveHistoricalLow << ' '
                  << toString(summary.currentPrice.currency)
                  << " above historical low ("
                  << recommendation.percentAboveHistoricalLow << "%), "
                  << recommendation.percentComparedToAverage
                  << "% vs average";
        if (recommendation.priceRangePositionPercent) {
            std::cout << ", range position="
                      << *recommendation.priceRangePositionPercent << '%';
        }
        std::cout << '\n';
        for (const auto& reason : recommendation.reasons) {
            std::cout << "  - " << reason << '\n';
        }
    }
    if (!foundHistory) std::cout << "No observations found in the requested period.\n";
    return foundHistory;
}

std::string databasePath() {
    const char* value = std::getenv("GAME_PRICE_DATABASE_PATH");
    return value ? value : GAME_PRICE_DATABASE_PATH;
}

void seedDemoHistory(
    const Game& game,
    StoreProductRepository& repository,
    const std::string& dataDirectory) {
    SteamProvider steam(dataDirectory + "/steam_products.txt");
    EpicGamesProvider epic(dataDirectory + "/epic_games_products.txt");
    GooglePlayProvider googlePlay(dataDirectory + "/google_play_products.txt");
    AppleAppStoreProvider apple(dataDirectory + "/apple_app_store_products.csv");
    NintendoEShopProvider nintendo(dataDirectory + "/nintendo_eshop_products.csv");

    std::vector<StoreProduct> products;
    for (const auto* provider : std::vector<const StoreProductProvider*>{
             &steam, &epic, &googlePlay, &apple, &nintendo}) {
        const auto storeProducts = provider->findProducts(game.id);
        products.insert(products.end(), storeProducts.begin(), storeProducts.end());
    }

    const std::vector<std::string> dates{
        "2026-01-01T12:00:00.000Z", "2026-02-01T12:00:00.000Z",
        "2026-03-01T12:00:00.000Z", "2026-04-01T12:00:00.000Z",
        "2026-05-01T12:00:00.000Z", "2026-06-01T12:00:00.000Z"};
    const std::vector<std::pair<Store, std::vector<std::int64_t>>> prices{
        {Store::Steam, {17500, 17500, 14000, 11200, 17500, 11200}},
        {Store::GooglePlay, {6500, 6500, 6500, 5900, 6500, 5500}},
        {Store::AppleAppStore, {6600, 6600, 5900, 6600, 6600, 5900}}};

    for (auto& product : products) {
        const auto series = std::find_if(prices.begin(), prices.end(),
            [&product](const auto& item) { return item.first == product.store; });
        if (series == prices.end()) continue;
        product.currentPrice.minorAmount = series->second.back();
        if (product.store == Store::Steam) {
            constexpr std::int64_t regularPriceWon = 17500;
            product.regularPrice = Money{regularPriceWon, Currency::KRW};
            product.discountPercent = static_cast<int>(
                (regularPriceWon - product.currentPrice.minorAmount) * 100 /
                regularPriceWon);
        }
    }
    repository.saveNormalizedProducts(game, products);

    std::size_t storedObservations = 0;
    for (const auto& product : products) {
        const auto series = std::find_if(prices.begin(), prices.end(),
            [&product](const auto& item) { return item.first == product.store; });
        if (series == prices.end()) continue;
        std::vector<PriceObservation> observations;
        for (std::size_t index = 0; index < dates.size(); ++index) {
            const auto currentPrice = series->second[index];
            if (product.store == Store::Steam) {
                constexpr std::int64_t regularPriceWon = 17500;
                observations.push_back(PriceObservation{
                    Money{currentPrice, Currency::KRW}, true, dates[index],
                    Money{regularPriceWon, Currency::KRW},
                    static_cast<int>(
                        (regularPriceWon - currentPrice) * 100 / regularPriceWon)});
            } else {
                observations.push_back(PriceObservation{
                    Money{currentPrice, Currency::KRW}, true, dates[index]});
            }
        }
        repository.replacePriceHistory(
            product.store, product.productId, observations);
        storedObservations += repository.findPriceHistory(
            product.store, product.productId).size();
    }
    std::cout << "Processed " << dates.size() << " monthly samples for "
              << products.size() << " Stores and stored " << storedObservations
              << " changed observations.\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    using namespace game_price;

    try {
        std::vector<std::string> arguments;
        for (int index = 1; index < argc; ++index) arguments.emplace_back(argv[index]);
        const auto options = parseCommandLine(arguments);
        if (options.command == AppCommand::Help) {
            std::cout << commandLineHelp();
            return static_cast<int>(AppExitCode::Success);
        }

        Database database(databasePath());
        StoreProductRepository repository(database);
        repository.initializeSchema();

        const std::string defaultDataDirectory = SAMPLE_DATA_DIR;
        GameCatalog catalog(catalogPath());
        GameQueryService queryService(catalog, repository);

        if (options.command == AppCommand::CollectionRuns) {
            return static_cast<int>(printCollectionRuns(queryService)
                                        ? AppExitCode::Success
                                        : AppExitCode::NoData);
        }

        if (options.command == AppCommand::Search) {
            const auto matches = queryService.searchGames(options.gameName);
            if (matches.empty()) {
                std::cout << "No games found for: " << options.gameName << '\n';
                return static_cast<int>(AppExitCode::NoData);
            }
            std::cout << "Games matching \"" << options.gameName << "\":\n";
            for (const auto& match : matches) {
                std::cout << "- " << match.title << " (" << match.id << ")\n";
            }
            return static_cast<int>(AppExitCode::Success);
        }

        if (options.command == AppCommand::CollectSteamAll) {
            std::cout << "Steam catalog collection:\n";
            const auto result = collectAllSteamProducts(
                catalog, repository, options.dataDirectory.value());
            std::cout << "Saved " << result.totalProducts
                      << " normalized Steam products to SQLite.\n";
            return static_cast<int>(
                collectionCompletedSuccessfully(result)
                    ? AppExitCode::Success
                    : AppExitCode::CollectionFailed);
        }
        if (options.command == AppCommand::CollectAppleAll) {
            std::cout << "Apple catalog collection:\n";
            const auto result = collectAllAppleProducts(
                catalog,
                repository,
                options.dataDirectory.value());
            std::cout << "Saved " << result.totalProducts
                      << " normalized Apple products to SQLite.\n";
            return static_cast<int>(
                collectionCompletedSuccessfully(result)
                    ? AppExitCode::Success
                    : AppExitCode::CollectionFailed);
        }

        const auto game = catalog.findByName(options.gameName);
        if (!game) {
            std::cout << "Game not found: " << options.gameName << '\n';
            return static_cast<int>(AppExitCode::GameNotFound);
        }

        if (options.command == AppCommand::SeedDemo) {
            seedDemoHistory(*game, repository, defaultDataDirectory);
            return static_cast<int>(AppExitCode::Success);
        }

        bool collectionSucceeded = true;
        if (options.command == AppCommand::CollectSteam) {
            collectionSucceeded = collectionCompletedSuccessfully(
                collectSteamProduct(
                    catalog, *game, repository, options.dataDirectory.value()));
            if (!collectionSucceeded) {
                return static_cast<int>(AppExitCode::CollectionFailed);
            }
            return static_cast<int>(AppExitCode::Success);
        }

        if (options.command == AppCommand::Collect || options.command == AppCommand::Demo) {
            collectionSucceeded = collectionCompletedSuccessfully(
                collectStoreProducts(
                    catalog,
                    *game,
                    repository,
                    options.dataDirectory.value_or(defaultDataDirectory)));
            if (options.command == AppCommand::Collect && !collectionSucceeded) {
                return static_cast<int>(AppExitCode::CollectionFailed);
            }
        }

        if (options.command == AppCommand::Compare) {
            const auto report = queryService.getGamePriceReport(options.gameName);
            const auto comparison = printPriceComparison(report);
            return static_cast<int>(comparison && comparison->cheapestProduct
                                        ? AppExitCode::Success
                                        : AppExitCode::NoData);
        }

        if (options.command == AppCommand::History) {
            const auto report = queryService.getGamePriceReport(
                options.gameName, options.historySince);
            if (!report || report->comparison.products.empty()) {
                std::cout << "No stored price history found for "
                          << options.gameName << ".\n";
                return static_cast<int>(AppExitCode::NoData);
            }
            return static_cast<int>(
                printPriceHistory(*report)
                    ? AppExitCode::Success
                    : AppExitCode::NoData);
        }

        if (options.command == AppCommand::Demo) {
            const auto report = queryService.getGamePriceReport(options.gameName);
            printPriceComparison(report);
            if (report) printPriceHistory(*report);
            if (!collectionSucceeded) {
                return static_cast<int>(AppExitCode::CollectionFailed);
            }
        }
    } catch (const std::invalid_argument& error) {
        std::cerr << "Error: " << error.what() << "\n\n" << commandLineHelp();
        return static_cast<int>(AppExitCode::UsageError);
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        return static_cast<int>(AppExitCode::RuntimeError);
    }

    return static_cast<int>(AppExitCode::Success);
}
