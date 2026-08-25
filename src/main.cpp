#include "game_price/app/command_line.h"
#include "game_price/app/game_query_service.h"
#include "game_price/catalog/game_catalog.h"
#include "game_price/collection/apple_app_store_provider.h"
#include "game_price/collection/collection_service.h"
#include "game_price/collection/google_play_provider.h"
#include "game_price/collection/steam_provider.h"
#include "game_price/persistence/database.h"
#include "game_price/persistence/store_product_repository.h"
#include "game_price/pricing/price_comparison_service.h"
#include "game_price/pricing/price_history_service.h"
#include "game_price/recommendation/purchase_recommendation_service.h"

#include <algorithm>
#include <functional>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace game_price;

CollectionResult collectStoreProducts(
    const Game& game,
    StoreProductRepository& repository,
    const std::string& dataDirectory) {
    SteamProvider steam(dataDirectory + "/steam_products.txt");
    GooglePlayProvider googlePlay(dataDirectory + "/google_play_products.txt");
    AppleAppStoreProvider appleAppStore(dataDirectory + "/apple_app_store_products.csv");
    std::vector<std::reference_wrapper<const StoreProductProvider>> providers{
        steam, googlePlay, appleAppStore};

    CollectionService service(repository, std::move(providers), 2);
    const auto result = service.collect(game);
    std::cout << "Collection runs:\n";
    for (const auto& run : result.runs) {
        std::cout << "- " << toString(run.store) << ": " << toString(run.status)
                  << ", attempt=" << run.attemptNumber
                  << ", products=" << run.productsFound;
        if (!run.errorMessage.empty()) std::cout << ", error=" << run.errorMessage;
        std::cout << '\n';
    }
    std::cout << "Saved " << result.totalProducts
              << " normalized products to SQLite.\n";
    return result;
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

        Database database(GAME_PRICE_DATABASE_PATH);
        StoreProductRepository repository(database);
        repository.initializeSchema();

        const std::string defaultDataDirectory = SAMPLE_DATA_DIR;
        GameCatalog catalog(defaultDataDirectory + "/games.txt");
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

        const auto game = catalog.findByName(options.gameName);
        if (!game) {
            std::cout << "Game not found: " << options.gameName << '\n';
            return static_cast<int>(AppExitCode::GameNotFound);
        }

        bool collectionSucceeded = true;
        if (options.command == AppCommand::Collect || options.command == AppCommand::Demo) {
            collectionSucceeded = collectionCompletedSuccessfully(
                collectStoreProducts(
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
