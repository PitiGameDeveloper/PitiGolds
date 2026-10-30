-- Recetas: al abrir la ventana de una profesión se guardan todas sus recetas
-- (conocidas o no), sus materiales, de dónde se sacan y cuáles conoce este personaje.
local ADDON, ns = ...

-- Campos de la receta que dependen del personaje; no van a la ficha compartida.
local PER_CHARACTER = {
  learned = true, craftable = true, numAvailable = true, favorite = true,
  relativeDifficulty = true, numSkillUps = true, canSkillUp = true, firstCraft = true,
  disabled = true, disabledReason = true, currentRecipeExperience = true,
  nextLevelRecipeExperience = true, unlockedRecipeLevel = true, earnedExperience = true,
}

-- Copia los valores simples de una tabla de la API. Así guardamos también los
-- campos que Forever añada y que todavía no conocemos.
local function CopyPrimitives(src, skip)
  local out = {}
  if type(src) ~= "table" then return out end
  for k, v in pairs(src) do
    local t = type(v)
    if type(k) == "string" and (t == "number" or t == "string" or t == "boolean")
        and not (skip and skip[k]) then
      out[k] = v
    end
  end
  return out
end

local function ReadSchematic(recipeID)
  local ok, s = pcall(C_TradeSkillUI.GetRecipeSchematic, recipeID, false)
  if not ok or type(s) ~= "table" then return nil end
  local reagents = {}
  for index, slot in ipairs(s.reagentSlotSchematics or {}) do
    local items, currencies = {}, {}
    for _, r in ipairs(slot.reagents or {}) do
      if r.itemID then
        items[#items + 1] = r.itemID
        ns.NoteItem(r.itemID, ns.ItemNameByID(r.itemID))
      elseif r.currencyID then
        currencies[#currencies + 1] = r.currencyID
      end
    end
    reagents[#reagents + 1] = {
      slot = slot.slotIndex or index,
      items = items,
      currencies = (#currencies > 0) and currencies or nil,
      qty = slot.quantityRequired,
      type = slot.reagentType,
      required = slot.required,
    }
  end
  if s.outputItemID then ns.NoteItem(s.outputItemID, ns.ItemNameByID(s.outputItemID)) end
  return {
    output = s.outputItemID,
    qtyMin = s.quantityMin,
    qtyMax = s.quantityMax,
    recipeType = s.recipeType,
    reagents = reagents,
  }
end

local busy, again = false, false
local lastScan = {}      -- professionID -> { time, skill }
local lastReported = {}  -- professionID -> recetas conocidas avisadas por el chat

local function ScanOpenProfession(force)
  local T = C_TradeSkillUI
  if not T or not T.GetAllRecipeIDs or not T.GetRecipeInfo then return end
  if busy then
    again = true
    return
  end
  if T.IsTradeSkillReady and not T.IsTradeSkillReady() then return end
  if (T.IsTradeSkillLinked and T.IsTradeSkillLinked())
      or (T.IsTradeSkillGuild and T.IsTradeSkillGuild())
      or (T.IsNPCCrafting and T.IsNPCCrafting()) then
    return -- es la profesión de otro jugador o de un PNJ
  end

  local base = T.GetBaseProfessionInfo and T.GetBaseProfessionInfo()
  local child = T.GetChildProfessionInfo and T.GetChildProfessionInfo()
  local prof = (child and (child.professionID or 0) > 0) and child or base
  if not prof or (prof.professionID or 0) == 0 then return end
  local profID = prof.professionID

  local previous = lastScan[profID]
  if not force and previous and time() - previous.time < 60 and previous.skill == prof.skillLevel then
    return -- nada nuevo desde hace menos de un minuto
  end

  local ids = T.GetAllRecipeIDs()
  if not ids or #ids == 0 then return end

  busy = true
  local db = PitiGoldsDB
  local known, difficulty = {}, {}
  local parentID = prof.parentProfessionID or (base and base.professionID)

  ns.RunChunked(#ids, 40, function(i)
    local id = ids[i]
    local info = T.GetRecipeInfo(id)
    if not info then return end
    local rec = db.recipes[id] or {}
    rec.name = info.name
    rec.professionID = profID
    rec.professionName = prof.professionName
    rec.parentProfessionID = parentID
    rec.categoryID = info.categoryID
    rec.info = CopyPrimitives(info, PER_CHARACTER)
    local schematic = ReadSchematic(id)
    if schematic then
      rec.output = schematic.output
      rec.qtyMin = schematic.qtyMin
      rec.qtyMax = schematic.qtyMax
      rec.recipeType = schematic.recipeType
      rec.reagents = schematic.reagents
    end
    if not info.learned and T.GetRecipeSourceText then
      local ok, source = pcall(T.GetRecipeSourceText, id)
      if ok and source and source ~= "" then rec.source = source end
    end
    if info.categoryID and not db.recipeCategories[info.categoryID] and T.GetCategoryInfo then
      local ok, cat = pcall(T.GetCategoryInfo, info.categoryID)
      if ok and type(cat) == "table" then
        db.recipeCategories[info.categoryID] = { name = cat.name, parent = cat.parentCategoryID }
      end
    end
    rec.updated = time()
    db.recipes[id] = rec
    if info.learned then
      known[#known + 1] = id
      difficulty[id] = info.relativeDifficulty
    end
  end, function()
    local c = ns.Char()
    c.professions[profID] = {
      name = prof.professionName,
      parentID = parentID,
      parentName = prof.parentProfessionName,
      skill = prof.skillLevel,
      maxSkill = prof.maxSkillLevel,
      modifier = prof.skillModifier,
      known = known,
      difficulty = difficulty,
      total = #ids,
      scanned = time(),
      info = CopyPrimitives(prof),
    }
    lastScan[profID] = { time = time(), skill = prof.skillLevel }
    busy = false
    if lastReported[profID] ~= #known then
      lastReported[profID] = #known
      ns.Print(("%s guardada: %d recetas conocidas de %d"):format(prof.professionName or "profesión", #known, #ids))
    end
    if again then
      again = false
      ns.Debounce("profscan", 1, function() ScanOpenProfession(false) end)
    end
  end, "profesiones", function()
    busy = false
  end)
end

local function ScanSoon(force)
  ns.Debounce(force and "profscan_force" or "profscan", 1.5, function() ScanOpenProfession(force) end)
end

ns.On("TRADE_SKILL_SHOW", function() ScanSoon(true) end)
ns.On("TRADE_SKILL_DATA_SOURCE_CHANGED", function() ScanSoon(true) end)
ns.On("NEW_RECIPE_LEARNED", function() ScanSoon(true) end)
ns.On("TRADE_SKILL_LIST_UPDATE", function() ScanSoon(false) end)
