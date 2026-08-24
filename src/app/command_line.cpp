#include "game_price/app/command_line.h"

#include <cctype>
#include <sstream>
#include <stdexcept>

namespace game_price {
namespace {

bool isIsoDate(const std::string& value) {
    if (value.size() != 10 || value[4] != '-' || value[7] != '-') return false;
    for (std::size_t index = 0; index < value.size(); ++index) {
        if (index == 4 || index == 7) continue;
        if (!std::isdigit(static_cast<unsigned char>(value[index]))) return false;
    }
    const int month = std::stoi(value.substr(5, 2));
    const int day = std::stoi(value.substr(8, 2));
    return month >= 1 && month <= 12 && day >= 1 && day <= 31;
}

std::string joinArguments(
    const std::vector<std::string>& arguments,
    std::size_t startIndex) {
    if (arguments.size() <= startIndex) return "Stardew Valley";

    std::ostringstream result;
    for (std::size_t index = startIndex; index < arguments.size(); ++index) {
        if (index > startIndex) result << ' ';
        result << arguments[index];
    }
    return result.str();
}

}  // namespace

CommandLineOptions parseCommandLine(const std::vector<std::string>& arguments) {
    if (arguments.empty()) return {};

    const auto& command = arguments.front();
    if (command == "--help" || command == "-h" || command == "help") {
        return CommandLineOptions{AppCommand::Help, "", std::nullopt, std::nullopt};
    }

    const std::string gameName = joinArguments(arguments, 1);
    if (command == "demo") {
        return CommandLineOptions{
            AppCommand::Demo, gameName, std::nullopt, std::nullopt};
    }
    if (command == "collect") {
        if (arguments.size() > 1 && arguments[1] == "--data-dir") {
            if (arguments.size() < 3 || arguments[2].empty()) {
                throw std::invalid_argument("collect --data-dir requires a directory path");
            }
            return CommandLineOptions{
                AppCommand::Collect,
                joinArguments(arguments, 3),
                std::nullopt,
                arguments[2]};
        }
        return CommandLineOptions{
            AppCommand::Collect, gameName, std::nullopt, std::nullopt};
    }
    if (command == "compare") {
        return CommandLineOptions{
            AppCommand::Compare, gameName, std::nullopt, std::nullopt};
    }
    if (command == "history") {
        if (arguments.size() > 1 && arguments[1] == "--since") {
            if (arguments.size() < 3) {
                throw std::invalid_argument("history --since requires YYYY-MM-DD");
            }
            if (!isIsoDate(arguments[2])) {
                throw std::invalid_argument("Invalid --since date: " + arguments[2]);
            }
            return CommandLineOptions{
                AppCommand::History,
                joinArguments(arguments, 3),
                arguments[2],
                std::nullopt};
        }
        return CommandLineOptions{
            AppCommand::History, gameName, std::nullopt, std::nullopt};
    }
    if (command == "runs") {
        return CommandLineOptions{
            AppCommand::CollectionRuns, "", std::nullopt, std::nullopt};
    }
    if (command == "search") {
        return CommandLineOptions{
            AppCommand::Search, gameName, std::nullopt, std::nullopt};
    }
    throw std::invalid_argument("Unknown command: " + command);
}

std::string commandLineHelp() {
    return
        "Usage: game_price_tracker [command] [game name]\n"
        "\n"
        "Commands:\n"
        "  demo      Collect, compare, and show history (default)\n"
        "  collect   Collect Store data and save it to SQLite\n"
        "            Optional: collect --data-dir PATH [game name]\n"
        "  compare   Compare prices already stored in SQLite\n"
        "  history   Show price history and purchase recommendations\n"
        "            Optional: history --since YYYY-MM-DD [game name]\n"
        "  runs      Show Store collection run history\n"
        "  search    Search the local game catalog by partial name\n"
        "  help      Show this help\n"
        "\n"
        "Default game name: Stardew Valley\n";
}

}  // namespace game_price
