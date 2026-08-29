#pragma once

#include "game_price/domain/game.h"
#include "game_price/domain/domain_types.h"

#include <optional>
#include <string>
#include <vector>
#include <shared_mutex>

namespace game_price {

struct CatalogStoreProduct {
    std::string gameId;
    Store store;
    std::string productId;
    std::string productUrl;
    std::vector<Platform> supportedPlatforms;
    Region region{Region::KR};
    GameEdition edition{GameEdition::Standard};
    OfferType offerType{OfferType::BaseGame};
    std::vector<PlatformCompatibility> compatibility;
};

class GameCatalog {
public:
    explicit GameCatalog(const std::string& dataPath);
    void reload(const std::string& dataPath);

    std::optional<Game> findByName(const std::string& name) const;
    std::optional<Game> findById(const std::string& id) const;
    std::vector<Game> searchByName(const std::string& query) const;
    std::vector<Game> allGames() const;
    std::vector<CatalogStoreProduct> storeProducts(Store store) const;
    std::optional<CatalogStoreProduct> findStoreProduct(
        Store store,
        const std::string& productId) const;

private:
    std::vector<Game> games_;
    std::vector<CatalogStoreProduct> storeProducts_;
    mutable std::shared_mutex mutex_;
};

}  // namespace game_price
