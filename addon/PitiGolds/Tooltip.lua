-- Añade al tooltip de cada objeto lo que ha calculado el motor: precio de mercado
-- en la subasta, mediana de los últimos 7 días y cuánto cuesta fabricarlo.
local ADDON, ns = ...

function ns.Money(copper)
  copper = tonumber(copper)
  if not copper then return "?" end
  -- Las pérdidas llevan el signo aparte: con módulo, -2 c saldría como 99p 98c.
  if copper < 0 then return "-" .. ns.Money(-copper) end
  if GetCoinTextureString then return GetCoinTextureString(copper) end
  local gold = math.floor(copper / 10000)
  local silver = math.floor((copper % 10000) / 100)
  local rest = copper % 100
  if gold > 0 then return ("%do %dp %dc"):format(gold, silver, rest) end
  if silver > 0 then return ("%dp %dc"):format(silver, rest) end
  return ("%dc"):format(rest)
end

local LABEL_R, LABEL_G, LABEL_B = 0.9, 0.7, 0.1
local BEST_R, BEST_G, BEST_B = 0.25, 1, 0.25
local AUCTION_CUT = 0.05 -- la subasta se queda el 5 % de lo vendido

-- Precio de venta que el juego iba a poner en cada tooltip (ya multiplicado por el montón).
-- Lo quitamos y lo ponemos nosotros como «Venta», junto a la subasta.
local sellPrice = {}

local function ItemSellPrice(itemID)
  local getInfo = (C_Item and C_Item.GetItemInfo) or GetItemInfo
  if not getInfo then return nil end
  local price = select(11, getInfo(itemID))
  if type(price) == "number" and price > 0 then return price end
end

-- Cuántas unidades hay en el montón que señala el ratón (bolsas, banco, correo, vendedor...).
local function StackCount(tooltip, itemID, sellTotal)
  local owner = tooltip.GetOwner and tooltip:GetOwner()
  if type(owner) == "table" then
    if owner.GetBagID and owner.GetID and C_Container and C_Container.GetContainerItemInfo then
      local ok, bag = pcall(owner.GetBagID, owner)
      local info = ok and bag and C_Container.GetContainerItemInfo(bag, owner:GetID())
      if info and info.stackCount and info.stackCount > 0 then return info.stackCount end
    end
    if type(owner.count) == "number" and owner.count > 0 then return owner.count end
  end
  -- Si no, lo sacamos del precio de venta del juego, que viene por el montón entero.
  local unit = ItemSellPrice(itemID)
  if sellTotal and unit and sellTotal % unit == 0 then return sellTotal / unit end
  return 1
end

local function PriceText(unit, count)
  if count > 1 then
    return ns.Money(unit) .. "  |cffccccccx" .. count .. ":|r " .. ns.Money(unit * count)
  end
  return ns.Money(unit)
end

local function AddLines(tooltip, itemID)
  local sellTotal = sellPrice[tooltip]
  sellPrice[tooltip] = nil
  local gen = PitiGoldsGenerated
  if not itemID then return end
  local price = type(gen) == "table" and gen.prices and gen.prices[itemID]
  local craft = type(gen) == "table" and gen.craft and gen.craft[itemID]
  local count = StackCount(tooltip, itemID, sellTotal)

  -- "mercado,mediana7d,tendencia" (tendencia: b = baja, s = sube)
  local market, median, trend
  if price then market, median, trend = price:match("^(%d*),(%d*),?(%a*)$") end
  market = tonumber(market)

  local sellUnit = sellTotal and (ItemSellPrice(itemID) or math.floor(sellTotal / count))
  -- En verde lo que más deja por unidad: la subasta, quitada su comisión, o el vendedor.
  local auctionWins = market and sellUnit and market * (1 - AUCTION_CUT) > sellUnit
  local sellWins = market and sellUnit and not auctionWins

  if sellTotal then
    local right = count > 1 and (ns.Money(sellUnit) .. "  |cffccccccx" .. count .. ":|r " .. ns.Money(sellTotal))
      or ns.Money(sellTotal)
    if sellWins then
      tooltip:AddDoubleLine("Venta:", right, BEST_R, BEST_G, BEST_B, 1, 1, 1)
    else
      tooltip:AddDoubleLine("Venta:", right, LABEL_R, LABEL_G, LABEL_B, 1, 1, 1)
    end
  end

  if market then
    local right = PriceText(market, count)
    if median ~= "" and tonumber(median) ~= market then
      right = right .. "  |cff999999(7 días: " .. ns.Money(median) .. ")|r"
    end
    if trend == "b" then
      right = right .. "  |cffff4040baja|r"
    elseif trend == "s" then
      right = right .. "  |cff40ff40sube|r"
    end
    if auctionWins then
      tooltip:AddDoubleLine("Subasta:", right, BEST_R, BEST_G, BEST_B, 1, 1, 1)
    else
      tooltip:AddDoubleLine("Subasta:", right, LABEL_R, LABEL_G, LABEL_B, 1, 1, 1)
    end
  end

  if craft then
    -- "coste,beneficio" de la receta conocida más barata
    local cost, profit = craft:match("^(%d+),(%-?%d+)$")
    if cost then
      local p = tonumber(profit)
      local result = (p >= 0 and "|cff40ff40+" or "|cffff4040-") .. ns.Money(math.abs(p)) .. "|r"
      tooltip:AddDoubleLine("PitiGolds fabricar", ns.Money(cost) .. "  " .. result,
        LABEL_R, LABEL_G, LABEL_B, 1, 1, 1)
    end
  end
end

if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
  local reported = false
  local function Report(err)
    if not reported then
      reported = true -- un tooltip falla en cada movimiento del ratón: basta con avisar una vez
      ns.ReportError("tooltip", err)
    end
  end

  -- Quitamos la línea «Precio de venta» del juego y nos guardamos el precio.
  -- Un precio con máximo (rango) se deja como está.
  local lineTypes = Enum.TooltipDataLineType
  if TooltipDataProcessor.AddLinePreCall and lineTypes and lineTypes.SellPrice then
    TooltipDataProcessor.AddLinePreCall(lineTypes.SellPrice, function(tooltip, lineData)
      local ok, hide = pcall(function()
        if not lineData.price and TooltipUtil and TooltipUtil.SurfaceArgs then TooltipUtil.SurfaceArgs(lineData) end
        local price, maxPrice = tonumber(lineData.price), tonumber(lineData.maxPrice)
        if not price or price <= 0 or (maxPrice and maxPrice > price) then return false end
        sellPrice[tooltip] = price
        return true
      end)
      if not ok then Report(hide) return end
      return hide or nil
    end)
  end
  -- Clientes que ponen el precio con el evento OnTooltipAddMoney en vez de como línea.
  if GameTooltip and GameTooltip.GetScript and GameTooltip.SetScript then
    local original = GameTooltip:GetScript("OnTooltipAddMoney")
    if original then
      GameTooltip:SetScript("OnTooltipAddMoney", function(self, cost, maxCost, ...)
        cost, maxCost = tonumber(cost), tonumber(maxCost)
        if cost and cost > 0 and not (maxCost and maxCost > cost) then
          sellPrice[self] = cost
          return
        end
        return original(self, cost, maxCost, ...)
      end)
    end
  end

  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
    local ok, err = pcall(AddLines, tooltip, data and data.id)
    if not ok then Report(err) end
  end)
end
