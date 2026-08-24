#include "game_price/app/command_line.h"
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

#include <functional>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace game_price;

void collectStoreProducts(
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
}

std::optional<PriceComparisonResult> printPriceComparison(
    const std::string& gameName,
    const GameCatalog& catalog,
    const StoreProductRepository& repository) {
    PriceComparisonService service(catalog, repository);
    const auto result = service.compareByGameName(gameName);
    if (!result) return std::nullopt;

    std::cout << result->game.title << " prices:\n";
    for (const auto& product : result->products) {
        std::cout << "- " << toString(product.store) << ": "
                  << product.currentPrice.minorAmount << ' '
                  << toString(product.currentPrice.currency) << '\n';
    }

    if (result->cheapestProduct) {
        std::cout << "Cheapest: " << toString(result->cheapestProduct->store)
                  << " - " << result->cheapestProduct->currentPrice.minorAmount
                  << ' ' << toString(result->cheapestProduct->currentPrice.currency) << '\n';
    } else {
        std::cout << "No purchasable product found in SQLite.\n";
    }
    return result;
}

void printPriceHistory(
    const PriceComparisonResult& comparison,
    const StoreProductRepository& repository) {
    PriceHistoryService historyService(repository);
    PurchaseRecommendationService recommendationService;
    std::cout << "Price history summary:\n";
    for (const auto& product : comparison.products) {
        const auto summary = historyService.analyze(product);
        if (!summary) continue;
        std::cout << "- " << toString(summary->store)
                  << ": current=" << summary->currentPrice.minorAmount
                  << ", low=" << summary->lowestPrice.minorAmount
                  << ", high=" << summary->highestPrice.minorAmount
                  << ", average=" << summary->averagePrice.minorAmount
                  << ' ' << toString(summary->currentPrice.currency)
                  << ", trend=" << toString(summary->trend)
                  << ", observations=" << summary->observationCount << '\n';

        const auto recommendation = recommendationService.recommend(*summary);
        std::cout << "  Recommendation: "
                  << toString(recommendation.recommendation) << '\n';
        for (const auto& reason : recommendation.reasons) {
            std::cout << "  - " << reason << '\n';
        }
    }
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
            return 0;
        }

        const std::string dataDirectory = SAMPLE_DATA_DIR;
        GameCatalog catalog(dataDirectory + "/games.txt");
        const auto game = catalog.findByName(options.gameName);
        if (!game) {
            std::cout << "Game not found: " << options.gameName << '\n';
            return 1;
        }

        Database database(GAME_PRICE_DATABASE_PATH);
        StoreProductRepository repository(database);
        repository.initializeSchema();

        if (options.command == AppCommand::Collect || options.command == AppCommand::Demo) {
            collectStoreProducts(*game, repository, dataDirectory);
        }

        if (options.command == AppCommand::Compare) {
            printPriceComparison(options.gameName, catalog, repository);
            return 0;
        }

        if (options.command == AppCommand::History) {
            const auto comparison = PriceComparisonService(catalog, repository)
                                        .compareByGameName(options.gameName);
            if (comparison) printPriceHistory(*comparison, repository);
            return 0;
        }

        if (options.command == AppCommand::Demo) {
            const auto comparison = printPriceComparison(options.gameName, catalog, repository);
            if (comparison) printPriceHistory(*comparison, repository);
        }
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        return 1;
    }

    return 0;
}
