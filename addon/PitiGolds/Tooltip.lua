-- Añade al tooltip de cada objeto lo que ha calculado el motor: precio de mercado
-- en la subasta, mediana de los últimos 7 días y cuánto cuesta fabricarlo.
local ADDON, ns = ...

function ns.Money(copper)
  copper = tonumber(copper)
  if not copper then return "?" end
  if GetCoinTextureString then return GetCoinTextureString(copper) end
  local gold = math.floor(copper / 10000)
  local silver = math.floor((copper % 10000) / 100)
  local rest = copper % 100
  if gold > 0 then return ("%do %dp %dc"):format(gold, silver, rest) end
  if silver > 0 then return ("%dp %dc"):format(silver, rest) end
  return ("%dc"):format(rest)
end

local LABEL_R, LABEL_G, LABEL_B = 0.9, 0.7, 0.1

local function AddLines(tooltip, itemID)
  local gen = PitiGoldsGenerated
  if not itemID or type(gen) ~= "table" then return end
  local price = gen.prices and gen.prices[itemID]
  local craft = gen.craft and gen.craft[itemID]

  if price then
    -- "mercado,mediana7d,tendencia" (tendencia: b = baja, s = sube)
    local market, median, trend = price:match("^(%d*),(%d*),?(%a*)$")
    if market and market ~= "" then
      local right = ns.Money(market)
      if median ~= "" and median ~= market then
        right = right .. "  |cff999999(7 días: " .. ns.Money(median) .. ")|r"
      end
      if trend == "b" then
        right = right .. "  |cffff4040baja|r"
      elseif trend == "s" then
        right = right .. "  |cff40ff40sube|r"
      end
      tooltip:AddDoubleLine("PitiGolds subasta", right, LABEL_R, LABEL_G, LABEL_B, 1, 1, 1)
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
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
    local ok, err = pcall(AddLines, tooltip, data and data.id)
    if not ok and not reported then
      reported = true -- un tooltip falla en cada movimiento del ratón: basta con avisar una vez
      ns.ReportError("tooltip", err)
    end
  end)
end
