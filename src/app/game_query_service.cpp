#include "game_price/app/game_query_service.h"

#include "game_price/pricing/price_history_service.h"
#include "game_price/recommendation/purchase_recommendation_service.h"
#include <unordered_map>

namespace game_price {

std::vector<PriceComparisonResult> GameQueryService::getCatalogComparisons(
    const std::vector<Game>& games, const PriceComparisonCriteria& criteria) const {
    std::vector<std::string> ids;
    ids.reserve(games.size());
    for (const auto& game : games) ids.push_back(game.id);
    std::unordered_map<std::string, std::vector<StoreProduct>> products;
    for (auto& product : repository_.findProductsByGameIds(ids))
        products[product.gameId].push_back(std::move(product));
    std::vector<PriceComparisonResult> results;
    results.reserve(games.size());
    for (const auto& game : games)
        results.push_back(PriceComparisonService::compareProducts(game, products[game.id], criteria));
    return results;
}

GameQueryService::GameQueryService(
    const GameCatalog& catalog,
    const StoreProductRepository& repository)
    : catalog_(catalog), repository_(repository) {}

std::vector<Game> GameQueryService::listGames() const {
    return catalog_.allGames();
}

std::vector<Game> GameQueryService::searchGames(const std::string& query) const {
    return catalog_.searchByName(query);
}

std::vector<Game> GameQueryService::filterGames(
    const GameCatalogFilter& filter) const {
    return catalog_.filterGames(filter);
}

std::optional<GamePriceReport> GameQueryService::getGamePriceReport(
    const std::string& gameName,
    const std::optional<std::string>& observedSince,
    const PriceComparisonCriteria& criteria) const {
    const auto comparison = PriceComparisonService(catalog_, repository_)
                                .compareByGameName(gameName, criteria);
    return buildReport(comparison, observedSince);
}

std::optional<GamePriceReport> GameQueryService::getGamePriceReportById(
    const std::string& gameId,
    const std::optional<std::string>& observedSince,
    const PriceComparisonCriteria& criteria) const {
    const auto comparison = PriceComparisonService(catalog_, repository_)
                                .compareByGameId(gameId, criteria);
    return buildReport(comparison, observedSince);
}

std::optional<GamePriceHistoryReport> GameQueryService::getGamePriceHistoryById(
    const std::string& gameId,
    const std::optional<std::string>& observedSince,
    const PriceComparisonCriteria& criteria) const {
    const auto comparison = PriceComparisonService(catalog_, repository_)
                                .compareByGameId(gameId,criteria);
    if (!comparison) return std::nullopt;

    std::vector<ProductPriceHistoryReport> histories;
    histories.reserve(comparison->products.size());
    for (const auto& product : comparison->products) {
        auto observations = observedSince
            ? repository_.findPriceHistorySince(
                  product.store, product.productId, *observedSince)
            : repository_.findPriceHistory(product.store, product.productId);
        std::string offerName;
        for (const auto& catalogProduct : catalog_.storeProducts(product.store)) {
            if (catalogProduct.gameId == comparison->game.id &&
                catalogProduct.productId == product.productId) {
                offerName = catalogProduct.offerName;
                break;
            }
        }
        histories.push_back(ProductPriceHistoryReport{
            product, std::move(offerName), std::move(observations)});
    }
    return GamePriceHistoryReport{comparison->game, std::move(histories)};
}

std::optional<GamePriceReport> GameQueryService::buildReport(
    const std::optional<PriceComparisonResult>& comparison,
    const std::optional<std::string>& observedSince) const {
    if (!comparison) return std::nullopt;

    PriceHistoryService historyService(repository_);
    PurchaseRecommendationService recommendationService;
    std::vector<ProductPriceReport> productReports;
    productReports.reserve(comparison->products.size());
    for (const auto& product : comparison->products) {
        const auto history = historyService.analyze(product, observedSince);
        std::string purchaseUrl;
        std::string offerName;
        for (const auto& catalogProduct : catalog_.storeProducts(product.store)) {
            if (catalogProduct.gameId == comparison->game.id &&
                catalogProduct.productId == product.productId) {
                purchaseUrl = catalogProduct.productUrl;
                offerName = catalogProduct.offerName;
                break;
            }
        }
        productReports.push_back(ProductPriceReport{
            product,
            std::move(purchaseUrl),
            std::move(offerName),
            history,
            history && product.freshness == PriceFreshness::Fresh
                ? std::optional<PurchaseRecommendationResult>{
                          recommendationService.recommend(*history)}
                : std::nullopt});
    }
    return GamePriceReport{*comparison, std::move(productReports)};
}

std::vector<CrawlRunRecord> GameQueryService::getCollectionRuns() const {
    return repository_.findCrawlRuns();
}

}  // namespace game_price
