/** `features/model-picker` — choisir un détecteur parmi vingt, au clavier compris. */

export {
  TIER_ORDER,
  flatOrder,
  groupByTier,
  modelSizeLabel,
  modelStateLabel,
  nextIndex,
  type TierGroup,
} from "./model/grouping";

export { ModelPicker } from "./ui/ModelPicker";
