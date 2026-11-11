-- Añade al tooltip de cada objeto lo que ha calculado el motor: precio de mercado
-- en la subasta, mediana de las últimas 36 horas y cuánto cuesta fabricarlo.
local ADDON, ns = ...

-- Iconos de moneda del juego. GetCoinTextureString ya no es global en todos los clientes
-- (en Forever no está y salía «5p 0c» en texto), así que se ponen a mano.
ns.coinIcons = ns.coinIcons or {
  gold = "|TInterface\\MoneyFrame\\UI-GoldIcon:0:0:2:0|t",
  silver = "|TInterface\\MoneyFrame\\UI-SilverIcon:0:0:2:0|t",
  copper = "|TInterface\\MoneyFrame\\UI-CopperIcon:0:0:2:0|t",
}

function ns.Money(copper)
  copper = tonumber(copper)
  if not copper then return "?" end
  copper = math.floor(copper + 0.5)
  -- Las pérdidas llevan el signo aparte: con módulo, -2 c saldría como 99p 98c.
  if copper < 0 then return "-" .. ns.Money(-copper) end
  local icons = ns.coinIcons
  local gold = math.floor(copper / 10000)
  local silver = math.floor((copper % 10000) / 100)
  local rest = copper % 100
  if gold > 0 then
    return ("%d%s %d%s %d%s"):format(gold, icons.gold, silver, icons.silver, rest, icons.copper)
  end
  if silver > 0 then return ("%d%s %d%s"):format(silver, icons.silver, rest, icons.copper) end
  return ("%d%s"):format(rest, icons.copper)
end

-- Precio de mercado de un objeto: lo último visto en la subasta si el motor aún no lo ha leído,
-- o el del motor.
function ns.MarketPrice(itemID)
  local seen = ns.ScanMarket and ns.ScanMarket(itemID)
  if seen then return seen, true end
  local gen = PitiGoldsGenerated
  local text = type(gen) == "table" and gen.prices and gen.prices[itemID]
  return text and tonumber(text:match("^(%d+)")), false
end

local LABEL_R, LABEL_G, LABEL_B = 0.9, 0.7, 0.1
local BEST_R, BEST_G, BEST_B = 0.25, 1, 0.25
local AUCTION_CUT = 0.05 -- la subasta se queda el 5 % de lo vendido

-- Lo que ya hemos puesto en cada tooltip para el objeto que enseña.
-- Las líneas se ponen en cuanto el juego da su precio de venta (lo quitamos y va como «Venta»),
-- o al final si el objeto no tiene precio de venta. Así no dependemos del orden en que el
-- cliente procesa las líneas ni de si llama a los post-calls tras quitar una.
local shown = {}
local hooked = {}

-- Marca lo puesto («pre»: con el precio de venta; «post»: al final) y lo olvida al vaciarse.
local function Mark(tooltip, itemID, by)
  shown[tooltip] = { id = itemID, by = by }
  if not hooked[tooltip] and tooltip.HookScript then
    hooked[tooltip] = true
    pcall(tooltip.HookScript, tooltip, "OnTooltipCleared", function(self) shown[self] = nil end)
  end
end

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

-- Lo que vale el montón que tienes (no uno lleno) y, entre paréntesis, la unidad.
local function PriceText(unit, count, total)
  if count > 1 then
    return ns.Money(total or unit * count) .. " |cffcccccc(" .. ns.Money(unit) .. ")|r"
  end
  return ns.Money(total or unit)
end

-- Cuántos tienes: este personaje en bolsas y banco, el banco de banda y tus otros personajes
-- (de esos, todo junto: bolsas, banco y buzón, según lo último que vio el addon).
local function CountIn(place, itemID)
  if type(place) ~= "table" then return 0 end
  local n = 0
  for _, list in ipairs({ place.items, place.bound }) do
    if type(list) == "table" then n = n + (list[itemID] or 0) end
  end
  return n
end

-- Nombre de un personaje guardado; con su reino si no es el tuyo.
function ns.CharDisplayName(key, c)
  local name = (type(c) == "table" and c.name) or key:match("^([^-]+)") or key
  local myRealm = ns.charKey and ns.charKey:match("%-(.+)$")
  local realm = key:match("%-(.+)$")
  if realm and myRealm and realm ~= myRealm then name = name .. " (" .. realm .. ")" end
  return name
end

function ns.OwnedCounts(itemID)
  local rows = {}
  local getCount = C_Item and C_Item.GetItemCount or GetItemCount
  local bags, bank = 0, 0
  if getCount then
    local ok, carried = pcall(getCount, itemID)
    bags = ok and carried or 0
    local okBank, all = pcall(getCount, itemID, true, false, true)
    bank = okBank and math.max(0, (all or 0) - bags) or 0
  end
  if bags > 0 then rows[#rows + 1] = { "Bolsas", bags } end
  if bank > 0 then rows[#rows + 1] = { "Banco", bank } end
  local db = PitiGoldsDB
  if type(db) == "table" then
    local warband = CountIn(db.account and db.account.warbandBank, itemID)
    if warband > 0 then rows[#rows + 1] = { "Banco de banda", warband } end
    local others = {}
    for key, c in pairs(db.characters or {}) do
      if key ~= ns.charKey and type(c) == "table" and type(c.inventory) == "table" then
        local inv = c.inventory
        local n = CountIn(inv.bags, itemID) + CountIn(inv.bank, itemID) + CountIn(inv.mail, itemID)
        if n > 0 then others[#others + 1] = { ns.CharDisplayName(key, c), n } end
      end
    end
    table.sort(others, function(a, b) return a[2] > b[2] end)
    for _, row in ipairs(others) do rows[#rows + 1] = row end
  end
  return rows
end

local function AddOwnedLines(tooltip, itemID)
  local rows = ns.OwnedCounts(itemID)
  if #rows == 0 then return end
  local total = 0
  for _, row in ipairs(rows) do total = total + row[2] end
  if #rows == 1 then
    tooltip:AddDoubleLine("Tienes:", total .. " |cffcccccc(" .. rows[1][1]:lower() .. ")|r",
      LABEL_R, LABEL_G, LABEL_B, 1, 1, 1)
    return
  end
  tooltip:AddDoubleLine("Tienes:", tostring(total), LABEL_R, LABEL_G, LABEL_B, 1, 1, 1)
  for _, row in ipairs(rows) do
    tooltip:AddDoubleLine("   " .. row[1], tostring(row[2]), 0.8, 0.8, 0.8, 0.8, 0.8, 0.8)
  end
end

local function AddLines(tooltip, itemID, sellTotal)
  local gen = PitiGoldsGenerated
  if not itemID then return end
  local price = type(gen) == "table" and gen.prices and gen.prices[itemID]
  local craft = type(gen) == "table" and gen.craft and gen.craft[itemID]
  local count = StackCount(tooltip, itemID, sellTotal)

  -- "mercado,mediana,tendencia,ventas" (mediana de 36 horas; tendencia: b = baja, s = sube;
  -- ventas: unidades vendidas al día, estimadas)
  local market, median, trend, sales
  if price then market, median, trend, sales = price:match("^(%d*),(%d*),?(%a*),?([%d%.]*)$") end
  market = tonumber(market)
  -- Lo que acabas de ver en la subasta manda sobre el precio del motor.
  local seen = ns.ScanMarket and ns.ScanMarket(itemID)
  if seen then market = seen end

  local sellUnit = sellTotal and (ItemSellPrice(itemID) or math.floor(sellTotal / count))
  -- En verde lo que más deja por unidad: la subasta, quitada su comisión, o el vendedor.
  local auctionWins = market and sellUnit and market * (1 - AUCTION_CUT) > sellUnit
  local sellWins = market and sellUnit and not auctionWins

  if sellTotal then
    local right = PriceText(sellUnit, count, sellTotal)
    if sellWins then
      tooltip:AddDoubleLine("Venta:", right, BEST_R, BEST_G, BEST_B, 1, 1, 1)
    else
      tooltip:AddDoubleLine("Venta:", right, LABEL_R, LABEL_G, LABEL_B, 1, 1, 1)
    end
  end

  if market then
    local right = PriceText(market, count)
    if median ~= "" and tonumber(median) ~= market then
      right = right .. "  |cff999999(36 horas: " .. ns.Money(median) .. ")|r"
    end
    if sales and sales ~= "" then
      right = right .. "  |cffccccccventas/día: " .. sales .. "|r"
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

  if ns.AddDisenchantLines then ns.AddDisenchantLines(tooltip, itemID) end
  AddOwnedLines(tooltip, itemID)
end

-- Objeto del tooltip mientras el juego lo está rellenando.
local function TooltipItemID(tooltip)
  local info = tooltip.processingInfo or tooltip.info
  local data = type(info) == "table" and info.tooltipData
  if type(data) == "table" and type(data.id) == "number" then return data.id end
  if tooltip.GetItem then
    local _, link, id = tooltip:GetItem()
    if type(id) == "number" then return id end
    if type(link) == "string" then return tonumber(link:match("item:(%d+)")) end
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

  -- Pone nuestras líneas con el precio de venta del juego. Devuelve true si lo ha hecho,
  -- y entonces quien llama quita la línea del juego. Un precio con máximo (rango) se deja.
  local function ShowWithSellPrice(tooltip, price, maxPrice)
    price, maxPrice = tonumber(price), tonumber(maxPrice)
    if not price or price <= 0 or (maxPrice and maxPrice > price) then return false end
    local itemID = TooltipItemID(tooltip)
    if not itemID then return false end
    AddLines(tooltip, itemID, price)
    Mark(tooltip, itemID, "pre")
    return true
  end

  -- Quitamos la línea «Precio de venta» del juego y ponemos las nuestras en su sitio.
  local lineTypes = Enum.TooltipDataLineType
  if TooltipDataProcessor.AddLinePreCall and lineTypes and lineTypes.SellPrice then
    TooltipDataProcessor.AddLinePreCall(lineTypes.SellPrice, function(tooltip, lineData)
      local ok, hide = pcall(function()
        if not lineData.price and TooltipUtil and TooltipUtil.SurfaceArgs then TooltipUtil.SurfaceArgs(lineData) end
        return ShowWithSellPrice(tooltip, lineData.price, lineData.maxPrice)
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
        local ok, done = pcall(function()
          -- Si el post-call ya puso la subasta, aquí solo falta la venta: dejamos la del juego.
          local mark = shown[self]
          if mark and mark.by == "post" and mark.id == TooltipItemID(self) then return false end
          return ShowWithSellPrice(self, cost, maxCost)
        end)
        if not ok then Report(done) end
        if ok and done then return end
        return original(self, cost, maxCost, ...)
      end)
    end
  end

  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
    local ok, err = pcall(function()
      local itemID = data and data.id
      if not itemID then return end
      local mark = shown[tooltip]
      if mark and mark.by == "pre" and mark.id == itemID then
        shown[tooltip] = nil -- ya está puesto; el siguiente refresco empieza de cero
        return
      end
      AddLines(tooltip, itemID)
      Mark(tooltip, itemID, "post")
    end)
    if not ok then Report(err) end
  end)
end
