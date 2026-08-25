#include "game_price/app/game_query_service.h"

#include "game_price/pricing/price_history_service.h"
#include "game_price/recommendation/purchase_recommendation_service.h"

namespace game_price {

GameQueryService::GameQueryService(
    const GameCatalog& catalog,
    const StoreProductRepository& repository)
    : catalog_(catalog), repository_(repository) {}

std::vector<Game> GameQueryService::searchGames(const std::string& query) const {
    return catalog_.searchByName(query);
}

std::optional<GamePriceReport> GameQueryService::getGamePriceReport(
    const std::string& gameName,
    const std::optional<std::string>& observedSince) const {
    const auto comparison = PriceComparisonService(catalog_, repository_)
                                .compareByGameName(gameName);
    return buildReport(comparison, observedSince);
}

std::optional<GamePriceReport> GameQueryService::getGamePriceReportById(
    const std::string& gameId,
    const std::optional<std::string>& observedSince) const {
    const auto comparison = PriceComparisonService(catalog_, repository_)
                                .compareByGameId(gameId);
    return buildReport(comparison, observedSince);
}

std::optional<GamePriceHistoryReport> GameQueryService::getGamePriceHistoryById(
    const std::string& gameId,
    const std::optional<std::string>& observedSince) const {
    const auto comparison = PriceComparisonService(catalog_, repository_)
                                .compareByGameId(gameId);
    if (!comparison) return std::nullopt;

    std::vector<ProductPriceHistoryReport> histories;
    histories.reserve(comparison->products.size());
    for (const auto& product : comparison->products) {
        auto observations = observedSince
            ? repository_.findPriceHistorySince(
                  product.store, product.productId, *observedSince)
            : repository_.findPriceHistory(product.store, product.productId);
        histories.push_back(
            ProductPriceHistoryReport{product, std::move(observations)});
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
        productReports.push_back(ProductPriceReport{
            product,
            history,
            history ? std::optional<PurchaseRecommendationResult>{
                          recommendationService.recommend(*history)}
                    : std::nullopt});
    }
    return GamePriceReport{*comparison, std::move(productReports)};
}

std::vector<CrawlRunRecord> GameQueryService::getCollectionRuns() const {
    return repository_.findCrawlRuns();
}

}  // namespace game_price
