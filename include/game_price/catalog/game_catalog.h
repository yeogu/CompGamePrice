#pragma once

#include "game_price/domain/game.h"
#include "game_price/domain/domain_types.h"

#include <optional>
#include <string>
#include <vector>

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

    std::optional<Game> findByName(const std::string& name) const;
    std::optional<Game> findById(const std::string& id) const;
    std::vector<Game> searchByName(const std::string& query) const;
    const std::vector<Game>& allGames() const noexcept;
    std::vector<CatalogStoreProduct> storeProducts(Store store) const;

private:
    std::vector<Game> games_;
    std::vector<CatalogStoreProduct> storeProducts_;
};

}  // namespace game_price
