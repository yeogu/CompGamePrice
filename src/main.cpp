#include "game_price/apple_app_store_provider.h"
#include "game_price/database.h"
#include "game_price/game_catalog.h"
#include "game_price/google_play_provider.h"
#include "game_price/price_comparison_service.h"
#include "game_price/price_history_service.h"
#include "game_price/purchase_recommendation_service.h"
#include "game_price/steam_provider.h"
#include "game_price/store_product_repository.h"

#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

int main() {
    using namespace game_price;

    try {
        const std::string dataDirectory = SAMPLE_DATA_DIR;
        GameCatalog catalog(dataDirectory + "/games.txt");
        SteamProvider steam(dataDirectory + "/steam_products.txt");
        GooglePlayProvider googlePlay(dataDirectory + "/google_play_products.txt");
        AppleAppStoreProvider appleAppStore(dataDirectory + "/apple_app_store_products.csv");

        std::vector<std::reference_wrapper<const StoreProductProvider>> providers{
            steam, googlePlay, appleAppStore};
        const auto game = catalog.findByName("Stardew Valley");
        if (!game) {
            std::cout << "Game not found.\n";
            return 1;
        }

        std::vector<StoreProduct> normalizedProducts;
        for (const auto& provider : providers) {
            const auto products = provider.get().findProducts(game->id);
            normalizedProducts.insert(
                normalizedProducts.end(), products.begin(), products.end());
        }

        Database database(GAME_PRICE_DATABASE_PATH);
        StoreProductRepository repository(database);
        repository.initializeSchema();
        repository.saveNormalizedProducts(*game, normalizedProducts);

        std::cout << "Saved " << normalizedProducts.size()
                  << " normalized products to SQLite.\n";

        PriceComparisonService service(catalog, repository);
        const auto result = service.compareByGameName("Stardew Valley");
        if (!result) {
            std::cout << "Game not found.\n";
            return 1;
        }

        std::cout << result->game.title << " prices:\n";
        for (const auto& product : result->products) {
            std::cout << "- " << toString(product.store) << ": "
                      << product.currentPrice.minorAmount << ' '
                      << toString(product.currentPrice.currency) << '\n';
        }

        if (!result->cheapestProduct) {
            std::cout << "No purchasable product found.\n";
            return 1;
        }

        std::cout << "Cheapest: " << toString(result->cheapestProduct->store)
                  << " - " << result->cheapestProduct->currentPrice.minorAmount
                  << ' ' << toString(result->cheapestProduct->currentPrice.currency) << '\n';

        PriceHistoryService historyService(repository);
        PurchaseRecommendationService recommendationService;
        std::cout << "Price history summary:\n";
        for (const auto& product : result->products) {
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
    } catch (const std::exception& error) {
        std::cerr << "Error: " << error.what() << '\n';
        return 1;
    }

    return 0;
}
