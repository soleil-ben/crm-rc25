/**
 * Visual AND/OR filter builder (Design.md section 8).
 *
 * The field catalogue comes from the API, so the builder can only offer fields and
 * operators the server actually accepts. The server validates the definition again
 * before compiling it.
 */

import { useT } from '../../i18n/index.jsx';
import { Button, Select, TextInput } from '../../components/ui/index.jsx';

const OPERATOR_LABELS = {
  contains: 'contains',
  not_contains: 'does not contain',
  equals: 'is',
  not_equals: 'is not',
  is_empty: 'is empty',
  is_not_empty: 'is recorded',
  in: 'is any of',
  not_in: 'is none of',
  gte: 'is at least',
  lte: 'is at most',
  between: 'is between',
  within_days: 'is within the last (days)',
  more_than_days_ago: 'is more than (days) ago',
  before: 'is before',
  after: 'is after',
  is: 'is',
  has_any: 'has any of',
  has_all: 'has all of',
  has_none: 'has none of',
};

function defaultValueFor(spec, operator) {
  if (['is_empty', 'is_not_empty'].includes(operator)) return null;
  if (spec.kind === 'boolean') return true;
  if (spec.kind === 'enum' || ['in', 'not_in'].includes(operator)) {
    return spec.options?.length ? [spec.options[0].value] : [];
  }
  if (spec.kind === 'tag') return [];
  if (spec.kind === 'number') return operator === 'between' ? [0, 10] : 1;
  if (spec.kind === 'date') {
    return ['within_days', 'more_than_days_ago'].includes(operator)
      ? 30
      : new Date().toISOString().slice(0, 10);
  }
  return '';
}

function ConditionRow({ condition, fields, tags, staff, onChange, onRemove }) {
  const t = useT();
  const spec = fields.find((field) => field.key === condition.field) || fields[0];

  function changeField(key) {
    const nextSpec = fields.find((field) => field.key === key);
    const operator = nextSpec.operators[0];
    onChange({ field: key, operator, value: defaultValueFor(nextSpec, operator) });
  }

  function changeOperator(operator) {
    onChange({ ...condition, operator, value: defaultValueFor(spec, operator) });
  }

  const optionList =
    spec.kind === 'tag'
      ? tags.map((tag) => ({ value: tag.id, label: tag.name }))
      : condition.field === 'owner_user_id'
        ? staff.map((member) => ({ value: member.id, label: member.full_name }))
        : spec.options;

  return (
    <div className="condition-row">
      <Select
        aria-label={t('segments.field')}
        value={condition.field}
        onChange={(event) => changeField(event.target.value)}
        options={fields.map((field) => ({ value: field.key, label: `${field.group}: ${field.label}` }))}
      />
      <Select
        aria-label={t('segments.operator')}
        value={condition.operator}
        onChange={(event) => changeOperator(event.target.value)}
        options={spec.operators.map((operator) => ({
          value: operator,
          label: OPERATOR_LABELS[operator] || operator,
        }))}
      />

      {/* Value editor varies by field kind. */}
      {['is_empty', 'is_not_empty'].includes(condition.operator) ? (
        <span className="meta">No value needed</span>
      ) : spec.kind === 'boolean' ? (
        <Select
          aria-label={t('segments.value')}
          value={condition.value ? 'true' : 'false'}
          onChange={(event) => onChange({ ...condition, value: event.target.value === 'true' })}
          options={[
            { value: 'true', label: t('common.yes') },
            { value: 'false', label: t('common.no') },
          ]}
        />
      ) : spec.kind === 'enum' || spec.kind === 'tag' || ['in', 'not_in'].includes(condition.operator) ? (
        <select
          className="select"
          multiple
          aria-label={t('segments.value')}
          value={(condition.value || []).map(String)}
          onChange={(event) =>
            onChange({
              ...condition,
              value: Array.from(event.target.selectedOptions).map((option) =>
                spec.kind === 'tag' || condition.field === 'owner_user_id'
                  ? Number(option.value)
                  : option.value,
              ),
            })
          }
          size={Math.min(4, Math.max(2, (optionList || []).length))}
        >
          {(optionList || []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : spec.kind === 'number' && condition.operator === 'between' ? (
        <div className="row">
          <TextInput
            type="number"
            aria-label="From"
            value={condition.value?.[0] ?? 0}
            onChange={(event) =>
              onChange({ ...condition, value: [Number(event.target.value), condition.value?.[1] ?? 0] })
            }
          />
          <TextInput
            type="number"
            aria-label="To"
            value={condition.value?.[1] ?? 0}
            onChange={(event) =>
              onChange({ ...condition, value: [condition.value?.[0] ?? 0, Number(event.target.value)] })
            }
          />
        </div>
      ) : spec.kind === 'number' || ['within_days', 'more_than_days_ago'].includes(condition.operator) ? (
        <TextInput
          type="number"
          min="0"
          aria-label={t('segments.value')}
          value={condition.value ?? 0}
          onChange={(event) => onChange({ ...condition, value: Number(event.target.value) })}
        />
      ) : spec.kind === 'date' ? (
        <TextInput
          type="date"
          aria-label={t('segments.value')}
          value={condition.value ?? ''}
          onChange={(event) => onChange({ ...condition, value: event.target.value })}
        />
      ) : (
        <TextInput
          aria-label={t('segments.value')}
          value={condition.value ?? ''}
          onChange={(event) => onChange({ ...condition, value: event.target.value })}
        />
      )}

      <Button variant="tertiary" compact onClick={onRemove} aria-label={t('segments.removeCondition')}>
        ✕
      </Button>
    </div>
  );
}

export function SegmentBuilder({ definition, fields, tags = [], staff = [], onChange, depth = 0 }) {
  const t = useT();

  function updateCondition(index, next) {
    const conditions = [...definition.conditions];
    conditions[index] = next;
    onChange({ ...definition, conditions });
  }

  function removeCondition(index) {
    const conditions = definition.conditions.filter((_, position) => position !== index);
    onChange({ ...definition, conditions: conditions.length ? conditions : [newCondition(fields)] });
  }

  return (
    <div className={depth === 0 ? 'segment-group' : 'segment-group segment-group--nested'}>
      <div className="row-wrap segment-group__header">
        <Select
          aria-label="Match mode"
          value={definition.match}
          onChange={(event) => onChange({ ...definition, match: event.target.value })}
          options={[
            { value: 'all', label: t('segments.matchAll') },
            { value: 'any', label: t('segments.matchAny') },
          ]}
          style={{ maxWidth: 230 }}
        />
      </div>

      <div className="stack">
        {definition.conditions.map((condition, index) =>
          condition.conditions ? (
            <SegmentBuilder
              key={index}
              definition={condition}
              fields={fields}
              tags={tags}
              staff={staff}
              depth={depth + 1}
              onChange={(next) => updateCondition(index, next)}
            />
          ) : (
            <ConditionRow
              key={index}
              condition={condition}
              fields={fields}
              tags={tags}
              staff={staff}
              onChange={(next) => updateCondition(index, next)}
              onRemove={() => removeCondition(index)}
            />
          ),
        )}
      </div>

      <div className="row">
        <Button
          compact
          onClick={() =>
            onChange({
              ...definition,
              conditions: [...definition.conditions, newCondition(fields)],
            })
          }
        >
          {t('segments.addCondition')}
        </Button>
        {depth < 2 && (
          <Button
            compact
            variant="tertiary"
            onClick={() =>
              onChange({
                ...definition,
                conditions: [
                  ...definition.conditions,
                  { match: definition.match === 'all' ? 'any' : 'all', conditions: [newCondition(fields)] },
                ],
              })
            }
          >
            {t('segments.addGroup')}
          </Button>
        )}
      </div>
    </div>
  );
}

export function newCondition(fields) {
  const spec = fields[0];
  const operator = spec.operators[0];
  return { field: spec.key, operator, value: defaultValueFor(spec, operator) };
}
