-- Datos del personaje: básicos, oro, resumen de profesiones, divisas,
-- reputaciones y descubrimiento de APIs nuevas de WoW Forever.
local ADDON, ns = ...

local function CollectBasics()
  local c = ns.Char()
  c.name = UnitName("player")
  c.realm = GetRealmName()
  c.faction = UnitFactionGroup("player")
  local _, classFile = UnitClass("player")
  c.class = classFile
  local _, raceFile = UnitRace("player")
  c.race = raceFile
  c.level = UnitLevel("player")
  c.guid = UnitGUID("player")
  c.lastSeen = time()
end

local function CollectMoney()
  local c = ns.Char()
  c.money = GetMoney()
  c.moneyUpdated = time()
  if C_Bank and C_Bank.FetchDepositedMoney and Enum.BankType and Enum.BankType.Account then
    local ok, amount = pcall(C_Bank.FetchDepositedMoney, Enum.BankType.Account)
    if ok and amount then
      PitiGoldsDB.account.warbandMoney = amount
      PitiGoldsDB.account.warbandMoneyUpdated = time()
    end
  end
end
ns.CollectMoney = CollectMoney

-- Resumen que da el libro de hechizos sin abrir ninguna ventana.
local function CollectProfessionSummary()
  if not GetProfessions then return end
  local p1, p2, arch, fish, cook = GetProfessions()
  local slots = { primary1 = p1, primary2 = p2, archaeology = arch, fishing = fish, cooking = cook }
  local list = {}
  for slot, index in pairs(slots) do
    local name, _, rank, maxRank, _, _, skillLine, modifier = GetProfessionInfo(index)
    if name then
      list[#list + 1] = {
        slot = slot, name = name, skillLine = skillLine,
        rank = rank, maxRank = maxRank, modifier = modifier,
      }
    end
  end
  local c = ns.Char()
  c.professionSummary = list
  c.professionSummaryUpdated = time()
end

-- Divisas -------------------------------------------------------------------
-- Se recorren los IDs uno a uno en lugar de la lista de la ventana de divisas,
-- que depende de qué cabeceras tenga el jugador plegadas.

local MAX_CURRENCY_ID = 5000

local function ReadCurrency(id)
  local info = C_CurrencyInfo.GetCurrencyInfo(id)
  if not info or not info.name or info.name == "" then return nil end
  if not info.discovered and (info.quantity or 0) == 0 then return nil end
  return {
    name = info.name,
    quantity = info.quantity,
    max = info.maxQuantity,
    earned = info.totalEarned,
    accountWide = info.isAccountWide or nil,
    transferable = info.isAccountTransferable or nil,
  }
end

local scanningCurrencies = false

local function ScanAllCurrencies()
  if scanningCurrencies or not (C_CurrencyInfo and C_CurrencyInfo.GetCurrencyInfo) then return end
  scanningCurrencies = true
  local found = {}
  ns.RunChunked(MAX_CURRENCY_ID, 500, function(id)
    local entry = ReadCurrency(id)
    if entry then found[id] = entry end
  end, function()
    local c = ns.Char()
    c.currencies = found
    c.currenciesUpdated = time()
    scanningCurrencies = false
  end, "divisas", function()
    scanningCurrencies = false
  end)
end

local function UpdateCurrency(id)
  local c = ns.Char()
  if not c.currencies then return end
  c.currencies[id] = ReadCurrency(id)
  c.currenciesUpdated = time()
end

-- Reputaciones ----------------------------------------------------------------
-- Solo se ven las facciones de cabeceras desplegadas en la ventana de reputación.

local function CollectReputations()
  if not (C_Reputation and C_Reputation.GetNumFactions and C_Reputation.GetFactionDataByIndex) then return end
  local reps = {}
  for i = 1, C_Reputation.GetNumFactions() do
    local f = C_Reputation.GetFactionDataByIndex(i)
    if f and f.factionID and f.factionID > 0 and (not f.isHeader or f.isHeaderWithRep) then
      reps[f.factionID] = {
        name = f.name,
        standing = f.currentStanding,
        reaction = f.reaction,
        min = f.currentReactionThreshold,
        max = f.nextReactionThreshold,
        accountWide = f.isAccountWide or nil,
      }
    end
  end
  local c = ns.Char()
  c.reputations = reps
  c.reputationsUpdated = time()
end

-- Descubrimiento --------------------------------------------------------------
-- Forever trae sistemas nuevos (Legacy, Merchant's Favor...) cuya API todavía no
-- conocemos. Se guardan los nombres de las funciones que parecen relacionadas
-- para poder programar su lectura después de verlas.

local PATTERNS = { "legacy", "favor", "merchant", "commerce", "crate", "campfire", "forever", "season" }

local function Matches(name)
  local lower = name:lower()
  for _, p in ipairs(PATTERNS) do
    if lower:find(p, 1, true) then return true end
  end
  return false
end

local function Discover()
  local _, build = GetBuildInfo()
  local previous = PitiGoldsDB.discovery
  if previous and previous.build == build then return end

  local namespaces, functions, globals, enums = {}, {}, {}, {}
  for key, value in pairs(_G) do
    if type(key) == "string" then
      if type(value) == "table" and key:match("^C_") then
        namespaces[#namespaces + 1] = key
        local nsMatches = Matches(key)
        for fname, fv in pairs(value) do
          if type(fv) == "function" and type(fname) == "string" and (nsMatches or Matches(fname)) then
            functions[#functions + 1] = key .. "." .. fname
          end
        end
      elseif type(value) == "function" and Matches(key) and #globals < 300 then
        globals[#globals + 1] = key
      end
    end
  end
  if type(Enum) == "table" then
    for key in pairs(Enum) do
      if type(key) == "string" and Matches(key) then enums[#enums + 1] = key end
    end
  end
  table.sort(namespaces)
  table.sort(functions)
  table.sort(globals)
  table.sort(enums)
  PitiGoldsDB.discovery = {
    build = build, time = time(),
    namespaces = namespaces, functions = functions, globals = globals, enums = enums,
  }
  ns.Log(("Descubrimiento: %d espacios C_, %d funciones y %d enums relacionados"):format(#namespaces, #functions, #enums))
end

-- Eventos -------------------------------------------------------------------

ns.On("PLAYER_LOGIN", function()
  CollectBasics()
  CollectMoney()
  CollectProfessionSummary()
  CollectReputations()
  Discover()
  -- Las divisas se recorren unos segundos después para no cargar la entrada al juego.
  C_Timer.After(5, ScanAllCurrencies)
end)

ns.On("PLAYER_MONEY", CollectMoney)

ns.On("PLAYER_LEVEL_UP", function(_, newLevel)
  ns.Char().level = newLevel or UnitLevel("player")
end)

ns.On("SKILL_LINES_CHANGED", function()
  ns.Debounce("profsummary", 2, CollectProfessionSummary)
end)

ns.On("CURRENCY_DISPLAY_UPDATE", function(_, currencyID)
  if currencyID then
    UpdateCurrency(currencyID)
  else
    ns.Debounce("currencies", 5, ScanAllCurrencies)
  end
end)

ns.On("UPDATE_FACTION", function()
  ns.Debounce("reputations", 3, CollectReputations)
end)

ns.On("PLAYER_LOGOUT", function()
  CollectMoney()
  ns.Char().lastSeen = time()
end)
