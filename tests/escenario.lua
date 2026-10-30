-- Datos de prueba: un brujo con herrería y minería, un alter y una subasta pequeña.

Mock.itemNames = {
  [2589] = "Paño de lino", [2592] = "Paño de lana", [818] = "Ojo de tigre", [5000] = "Basura gris",
  [2840] = "Barra de cobre", [2845] = "Hacha de cobre", [2770] = "Mineral de cobre", [2841] = "Barra de bronce",
  [2880] = "Flujo débil", [2320] = "Hilo grueso", [19019] = "Furia del Viento",
}
-- Lo que paga el vendedor por unidad.
Mock.sellPrices = {
  [2589] = 13, [2592] = 33, [818] = 150, [5000] = 500, [2840] = 10, [2845] = 18, [2770] = 5,
}

Mock.merchant.items = {
  { itemID = 2880, name = "Flujo débil", price = 100 },
  { itemID = 2320, name = "Hilo grueso", price = 30, stack = 3 },
  { itemID = 9999, name = "Diseño: Yelmo de bronce", price = 0, costs = {
    { value = 50, link = "|cffffffff|Hcurrency:3001|h[Favor del mercader]|h|r", currencyName = "Favor del mercader" },
  } },
}

local function link(name) return "|cffffffff|Hitem:1::::::::60:::::|h[" .. name .. "]|h|r" end

Mock.bags = {
  [0] = {
    numSlots = 16,
    [1] = { itemID = 2589, stackCount = 20, hyperlink = link("Paño de lino") },
    [2] = { itemID = 2770, stackCount = 15, hyperlink = link("Mineral de cobre") },
    [3] = { itemID = 6948, stackCount = 1, isBound = true, hyperlink = link("Piedra de hogar") },
    [5] = { itemID = 5000, stackCount = 4, hyperlink = link("Basura gris") },
  },
  [1] = { numSlots = 10, [4] = { itemID = 2589, stackCount = 5, hyperlink = link("Paño de lino") } },
  [-1] = { numSlots = 28, [1] = { itemID = 2589, stackCount = 40, hyperlink = link("Paño de lino") } },
  [6] = { numSlots = 10, [1] = { itemID = 2840, stackCount = 10, hyperlink = link("Barra de cobre") } },
  [13] = { numSlots = 98, [1] = { itemID = 818, stackCount = 3, hyperlink = link("Ojo de tigre") } },
}
Mock.warbandMoney = 500000

Mock.currencies = {
  [42] = { name = "Divisa vieja", quantity = 0, discovered = false },
  [3001] = { name = "Favor del mercader", quantity = 120, discovered = true, maxQuantity = 0, totalEarned = 150 },
  [3002] = { name = "Puntos de legado", quantity = 16, discovered = true, isAccountWide = true },
}

Mock.factions = {
  { factionID = 0, name = "Forever", isHeader = true },
  { factionID = 2900, name = "Autoridad de Comercio de Azeroth", currentStanding = 1500, reaction = 5,
    currentReactionThreshold = 0, nextReactionThreshold = 3000 },
}

Mock.professions = {
  [1] = { name = "Herrería", rank = 75, maxRank = 150, skillLine = 164 },
  [2] = { name = "Minería", rank = 80, maxRank = 150, skillLine = 186 },
  [5] = { name = "Cocina", rank = 1, maxRank = 75, skillLine = 185 },
}

Mock.tradeSkill.base = { professionID = 164, professionName = "Herrería" }
Mock.tradeSkill.child = {
  professionID = 2751, professionName = "Herrería de Forever", parentProfessionID = 164,
  parentProfessionName = "Herrería", skillLevel = 75, maxSkillLevel = 150, skillModifier = 0,
}
Mock.tradeSkill.recipes = {
  [1001] = { recipeID = 1001, name = "Fundir cobre", learned = true, categoryID = 10,
             relativeDifficulty = 1, numSkillUps = 1, maxTrivialLevel = 50 },
  [1002] = { recipeID = 1002, name = "Hacha de cobre", learned = true, categoryID = 11, relativeDifficulty = 0 },
  [1003] = { recipeID = 1003, name = "Yelmo de bronce", learned = false, categoryID = 11 },
}
Mock.tradeSkill.schematics = {
  [1001] = { outputItemID = 2840, quantityMin = 1, quantityMax = 1, reagentSlotSchematics = {
    { reagents = { { itemID = 2770 } }, quantityRequired = 1, reagentType = 1, slotIndex = 1, required = true },
  } },
  [1002] = { outputItemID = 2845, quantityMin = 1, quantityMax = 1, reagentSlotSchematics = {
    { reagents = { { itemID = 2840 } }, quantityRequired = 6, reagentType = 1, slotIndex = 1, required = true },
    { reagents = { { itemID = 2880 } }, quantityRequired = 1, reagentType = 1, slotIndex = 2, required = true },
    { reagents = { { itemID = 2589 } }, quantityRequired = 1, reagentType = 0, slotIndex = 3, required = false },
  } },
  [1003] = { outputItemID = 2846, quantityMin = 1, quantityMax = 1, reagentSlotSchematics = {
    { reagents = { { itemID = 2841 } }, quantityRequired = 6, reagentType = 1, slotIndex = 1, required = true },
    { reagents = { { currencyID = 3001 } }, quantityRequired = 10, reagentType = 1, slotIndex = 2, required = true },
  } },
}
Mock.tradeSkill.sources = {
  [1003] = "|cffffd200Vendedor: |rGrimtak|n|cffffd200Zona: |rDurotar|n|cffffd200Coste: |r5|TInterface\\MoneyFrame\\UI-SilverIcon:0:0:2:0|t",
}

Mock.inbox = {
  { sender = "Subasta", subject = "Venta", money = 5000, items = {
    { name = "Paño de lana", itemID = 2592, count = 20 },
  } },
  { sender = "Otro", subject = "Contra reembolso", cod = 100, items = {
    { name = "Mineral de cobre", itemID = 2770, count = 5 },
  } },
}

Mock.replicate = {
  { itemID = 2589, count = 20, buyout = 20 * 45, owner = "Vendedor1", name = "Paño de lino" },
  { itemID = 2589, count = 10, buyout = 10 * 40, owner = "Vendedor2", name = "Paño de lino" },
  { itemID = 2589, count = 5, buyout = 5 * 40, owner = "Vendedor1", name = "Paño de lino" },
  { itemID = 2770, count = 20, buyout = 20 * 120, owner = "Minero", name = "Mineral de cobre" },
  { itemID = 2845, count = 1, buyout = 5000, owner = "Herrero", name = "Hacha de cobre" },
  { itemID = 19019, count = 1, buyout = 75000000000, owner = "Rico", name = "Furia del Viento" },
  { itemID = 2592, count = 1, buyout = 0, owner = "Pujador", name = "Paño de lana" },
}

Mock.browseData = {
  [7] = {
    { itemKey = { itemID = 2589 }, minPrice = 40, totalQuantity = 35 },
    { itemKey = { itemID = 2592 }, minPrice = 90, totalQuantity = 100 },
    { itemKey = { itemID = 2770 }, minPrice = 120, totalQuantity = 20 },
    { itemKey = { itemID = 2840 }, minPrice = 300, totalQuantity = 50 },
    { itemKey = { itemID = 818 }, minPrice = 2500, totalQuantity = 4 },
    { itemKey = { itemID = 5000 }, minPrice = 300, totalQuantity = 50 },
  },
  [0] = { { itemKey = { itemID = 118 }, minPrice = 50, totalQuantity = 200 } },
}

Mock.owned = {
  { itemKey = { itemID = 2840 }, quantity = 10, buyoutAmount = 3500, status = 0, timeLeftSeconds = 40000,
    itemLink = link("Barra de cobre") },
  { itemKey = { itemID = 2589 }, quantity = 20, buyoutAmount = 900, status = 1, timeLeftSeconds = 0 },
}

Mock.sendItems = { { name = "Barra de cobre", itemID = 2840, count = 5 } }
