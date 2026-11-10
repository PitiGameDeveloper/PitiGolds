-- Lo que sale al desencantar un objeto y lo que vale en la subasta, para el tooltip.
-- Las probabilidades son las de la tabla clásica de desencantar (por calidad, nivel de objeto
-- y si es arma o armadura); Forever usa los objetos de entonces. El precio de cada material es
-- lo último visto en la subasta o el del motor.
local ADDON, ns = ...

-- Materiales
local STRANGE, SOUL, VISION, DREAM, ILLUSION = 10940, 11083, 11137, 11176, 16204
local LMAGIC, GMAGIC, LASTRAL, GASTRAL = 10938, 10939, 10998, 11082
local LMYSTIC, GMYSTIC, LNETHER, GNETHER, LETERNAL, GETERNAL = 11134, 11135, 11174, 11175, 16202, 16203
local SGLIMMER, LGLIMMER, SGLOW, LGLOW = 10978, 11084, 11138, 11139
local SRADIANT, LRADIANT, SBRILLIANT, LBRILLIANT, NEXUS = 11177, 11178, 14343, 14344, 20725

-- Verdes (armadura): { nivel máximo, { polvo, min, max, % }, { esencia, min, max, % }, { fragmento, % } }
-- En las armas se cambian las probabilidades del polvo y la esencia.
local UNCOMMON = {
  { 15, { STRANGE, 1, 2, 80 }, { LMAGIC, 1, 2, 20 } },
  { 20, { STRANGE, 2, 3, 75 }, { GMAGIC, 1, 2, 20 }, { SGLIMMER, 5 } },
  { 25, { STRANGE, 4, 6, 75 }, { LASTRAL, 1, 2, 15 }, { SGLIMMER, 10 } },
  { 30, { SOUL, 1, 2, 75 }, { GASTRAL, 1, 2, 20 }, { LGLIMMER, 5 } },
  { 35, { SOUL, 2, 5, 75 }, { LMYSTIC, 1, 2, 20 }, { SGLOW, 5 } },
  { 40, { VISION, 1, 2, 75 }, { GMYSTIC, 1, 2, 20 }, { LGLOW, 5 } },
  { 45, { VISION, 2, 5, 75 }, { LNETHER, 1, 2, 20 }, { SRADIANT, 5 } },
  { 50, { DREAM, 1, 2, 75 }, { GNETHER, 1, 2, 20 }, { LRADIANT, 5 } },
  { 55, { DREAM, 2, 5, 75 }, { LETERNAL, 1, 2, 20 }, { SBRILLIANT, 5 } },
  { 60, { ILLUSION, 1, 2, 75 }, { GETERNAL, 1, 2, 20 }, { LBRILLIANT, 5 } },
  { 65, { ILLUSION, 2, 5, 75 }, { GETERNAL, 2, 3, 20 }, { LBRILLIANT, 5 } },
}

-- Azules: { nivel máximo, fragmento } (100 %; desde el 56, 0,5 % de cristal de nexo).
local RARE = {
  { 25, SGLIMMER }, { 30, LGLIMMER }, { 35, SGLOW }, { 40, LGLOW }, { 45, SRADIANT },
  { 50, LRADIANT }, { 55, SBRILLIANT }, { 65, LBRILLIANT },
}

-- Morados: { nivel máximo, material, min, max }
local EPIC = {
  { 45, SRADIANT, 2, 4 }, { 50, LRADIANT, 2, 4 }, { 55, SBRILLIANT, 2, 4 },
  { 60, NEXUS, 1, 1 }, { 80, NEXUS, 1, 2 },
}

local WEAPON, ARMOR = 2, 4
local NOT_DISENCHANTABLE = { INVTYPE_BODY = true, INVTYPE_TABARD = true, INVTYPE_NON_EQUIP_IGNORE = true }

local function Pick(list, level)
  for _, row in ipairs(list) do
    if level <= row[1] then return row end
  end
end

-- Lista de { itemID, min, max, chance (0-1) }, o nil si no se puede desencantar.
function ns.DisenchantOutcomes(itemID)
  local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
  if not getInfo then return nil end
  local name, _, quality, level, _, _, _, _, equipLoc, _, _, classID = getInfo(itemID)
  if not name or type(quality) ~= "number" or type(level) ~= "number" then return nil end
  if classID ~= WEAPON and classID ~= ARMOR then return nil end
  if not equipLoc or equipLoc == "" or NOT_DISENCHANTABLE[equipLoc] then return nil end
  local out = {}
  if quality == 2 then
    local row = level >= 5 and Pick(UNCOMMON, level)
    if not row then return nil end
    local dust, essence, shard = row[2], row[3], row[4]
    local dustChance, essenceChance = dust[4], essence[4]
    if classID == WEAPON then dustChance, essenceChance = essenceChance, dustChance end
    out[#out + 1] = { dust[1], dust[2], dust[3], dustChance / 100 }
    out[#out + 1] = { essence[1], essence[2], essence[3], essenceChance / 100 }
    if shard then out[#out + 1] = { shard[1], 1, 1, shard[2] / 100 } end
  elseif quality == 3 then
    local row = level >= 11 and Pick(RARE, level)
    if not row then return nil end
    if level >= 56 then
      out[#out + 1] = { row[2], 1, 1, 0.995 }
      out[#out + 1] = { NEXUS, 1, 1, 0.005 }
    else
      out[#out + 1] = { row[2], 1, 1, 1 }
    end
  elseif quality == 4 then
    local row = level >= 40 and Pick(EPIC, level)
    if not row then return nil end
    out[#out + 1] = { row[2], row[3], row[4], 1 }
  else
    return nil
  end
  return out
end

local function Pct(chance)
  local pct = chance * 100
  if pct == math.floor(pct) then return ("%d %%"):format(pct) end
  return ("%.1f %%"):format(pct)
end

-- Valor esperado de desencantar una unidad y las líneas de cada material.
function ns.AddDisenchantLines(tooltip, itemID)
  local outcomes = ns.DisenchantOutcomes(itemID)
  if not outcomes then return end
  local total, missing, rows = 0, false, {}
  for _, o in ipairs(outcomes) do
    local mat, min, max, chance = o[1], o[2], o[3], o[4]
    local price = ns.MarketPrice and ns.MarketPrice(mat)
    local amount = min == max and tostring(min) or (min .. "-" .. max)
    local name = ns.ItemNameByID(mat)
    if not name then
      if C_Item and C_Item.RequestLoadItemDataByID then pcall(C_Item.RequestLoadItemDataByID, mat) end
      name = "objeto " .. mat
    end
    if price then
      total = total + chance * (min + max) / 2 * price
    else
      missing = true
    end
    rows[#rows + 1] = {
      ("   %s x%s |cff999999(%s)|r"):format(name, amount, Pct(chance)),
      price and ns.Money(price) or "|cff999999sin precio|r",
    }
  end
  local right = total > 0 and ("~" .. ns.Money(total) .. (missing and "+" or "")) or "|cff999999sin precio|r"
  tooltip:AddDoubleLine("Desencantar:", right, 0.9, 0.7, 0.1, 1, 1, 1)
  for _, row in ipairs(rows) do
    tooltip:AddDoubleLine(row[1], row[2], 0.8, 0.8, 0.8, 1, 1, 1)
  end
end
