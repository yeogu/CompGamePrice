#include "game_price/notification/alert_service.h"
#include "game_price/domain/store_product.h"
#include "game_price/pricing/price_comparison_service.h"

#include <sqlite3.h>
#include <stdexcept>

namespace game_price {
namespace {
void bindText(sqlite3_stmt* s,int i,const std::string& v){sqlite3_bind_text(s,i,v.c_str(),-1,SQLITE_TRANSIENT);}
}
AlertService::AlertService(AccountRepository& repository):repository_(repository){}
std::size_t AlertService::evaluateGame(const std::string& gameId) const {
    sqlite3* db=repository_.database().handle();
    const char* sql=R"sql(
      SELECT r.id,r.user_id,r.rule_type,r.target_price_minor,p.store,p.external_product_id,
             p.price_minor,p.currency,
             (SELECT COUNT(*) FROM price_history h WHERE h.store=p.store AND h.external_product_id=p.external_product_id AND h.purchasable=1),
             (SELECT MIN(h.price_minor) FROM price_history h WHERE h.store=p.store AND h.external_product_id=p.external_product_id AND h.purchasable=1),
             (SELECT CAST(AVG(h.price_minor) AS INTEGER) FROM price_history h WHERE h.store=p.store AND h.external_product_id=p.external_product_id AND h.purchasable=1),
             (SELECT h.price_minor FROM price_history h WHERE h.store=p.store AND h.external_product_id=p.external_product_id AND h.purchasable=1 ORDER BY h.observed_at DESC,h.id DESC LIMIT 1 OFFSET 1),
             (SELECT h.observed_at FROM price_history h WHERE h.store=p.store AND h.external_product_id=p.external_product_id AND h.purchasable=1 ORDER BY h.observed_at DESC,h.id DESC LIMIT 1)
      FROM alert_rules r JOIN store_products p ON p.game_id=r.game_id
      WHERE r.game_id=? AND r.active=1 AND p.purchasable=1
      AND p.region=? AND p.edition=? AND p.offer_type=? AND p.currency=?
      AND p.last_successful_check_at IS NOT NULL
      AND p.last_successful_check_at >=
          strftime('%Y-%m-%dT%H:%M:%fZ','now',?)
      AND (r.platform IS NULL OR EXISTS(
            SELECT 1 FROM product_platforms pp
            WHERE pp.store=p.store AND pp.external_product_id=p.external_product_id
              AND pp.platform=r.platform)
          OR EXISTS(
            SELECT 1 FROM product_compatibility pc
            WHERE pc.store=p.store AND pc.external_product_id=p.external_product_id
              AND pc.platform=r.platform AND pc.status IN ('Native','Compatible')));
    )sql";
    sqlite3_stmt* row=nullptr; if(sqlite3_prepare_v2(db,sql,-1,&row,nullptr)!=SQLITE_OK) throw std::runtime_error(sqlite3_errmsg(db));
    const PriceComparisonCriteria defaultCriteria;
    bindText(row,1,gameId);
    bindText(row,2,toString(defaultCriteria.region));
    bindText(row,3,toString(defaultCriteria.edition));
    bindText(row,4,toString(defaultCriteria.offerType));
    bindText(row,5,toString(defaultCriteria.currency));
    bindText(row,6,"-"+std::to_string(PriceStaleAfterHours)+" hours");
    std::size_t created=0;
    while(sqlite3_step(row)==SQLITE_ROW){
        const auto type=alertRuleTypeFromString(reinterpret_cast<const char*>(sqlite3_column_text(row,2)));
        const auto price=sqlite3_column_int64(row,6); const auto count=sqlite3_column_int64(row,8);
        bool matches=false;
        if(type==AlertRuleType::BelowTargetPrice) matches=sqlite3_column_type(row,3)!=SQLITE_NULL && price<=sqlite3_column_int64(row,3);
        else if(type==AlertRuleType::PriceDrop) matches=count>=2 && sqlite3_column_type(row,11)!=SQLITE_NULL && price<sqlite3_column_int64(row,11);
        else if(type==AlertRuleType::NewHistoricalLow) matches=count>=2 && price==sqlite3_column_int64(row,9) && sqlite3_column_type(row,11)!=SQLITE_NULL && price<sqlite3_column_int64(row,11);
        else if(type==AlertRuleType::BelowAverage) matches=count>=2 && price<sqlite3_column_int64(row,10);
        if(!matches) continue;
        sqlite3_stmt* insert=nullptr;
        sqlite3_prepare_v2(db,R"sql(
          INSERT OR IGNORE INTO notifications(user_id,rule_id,game_id,store,external_product_id,price_minor,currency,message,event_key)
          VALUES(?,?,?,?,?,?,?, ?, ?);
        )sql",-1,&insert,nullptr);
        sqlite3_bind_int64(insert,1,sqlite3_column_int64(row,1)); sqlite3_bind_int64(insert,2,sqlite3_column_int64(row,0));
        bindText(insert,3,gameId); bindText(insert,4,reinterpret_cast<const char*>(sqlite3_column_text(row,4)));
        bindText(insert,5,reinterpret_cast<const char*>(sqlite3_column_text(row,5))); sqlite3_bind_int64(insert,6,price);
        bindText(insert,7,reinterpret_cast<const char*>(sqlite3_column_text(row,7)));
        bindText(insert,8,"가격 알림 조건을 충족했습니다.");
        bindText(insert,9,std::to_string(sqlite3_column_int64(row,0))+":"+
            reinterpret_cast<const char*>(sqlite3_column_text(row,12))+":"+
            reinterpret_cast<const char*>(sqlite3_column_text(row,4))+":"+
            reinterpret_cast<const char*>(sqlite3_column_text(row,5)));
        if(sqlite3_step(insert)==SQLITE_DONE && sqlite3_changes(db)>0) ++created;
        sqlite3_finalize(insert);
    }
    sqlite3_finalize(row); return created;
}
}  // namespace game_price
