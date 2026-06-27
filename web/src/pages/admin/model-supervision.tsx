// Eurelis — Page admin de supervision des modèles configurés par tenant.
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import {
  LucideCheck,
  LucideCopy,
  LucidePlus,
  LucideTrash2,
  LucideX,
} from 'lucide-react';

import Spotlight from '@/components/spotlight';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import {
  type CompareResult,
  compareTenantModels,
  copyModelDefaults,
  copyModelInstance,
  deleteModelInstance,
} from '@/services/admin-model-supervision-service';
import { listTenants } from '@/services/admin-service';

const ModelSupervisionKeys = {
  tenants: () => ['admin/modelSupervision/tenants'] as const,
  compare: (ids: string[]) =>
    ['admin/modelSupervision/compare', [...ids].sort().join(',')] as const,
};

const EMPTY = '—';

type ActionKind = 'copyInstance' | 'deleteInstance' | 'copyDefaults';

interface ActionState {
  kind: ActionKind;
  providerName?: string;
  instanceName?: string;
  presentTenantIds: string[];
}

function ModelSupervisionPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [pickerFilter, setPickerFilter] = useState('');
  const [modelFilter, setModelFilter] = useState('');
  const [action, setAction] = useState<ActionState | null>(null);
  const [actionSource, setActionSource] = useState<string>('');
  const [actionTargets, setActionTargets] = useState<Set<string>>(new Set());

  const { data: tenantsResp } = useQuery({
    queryKey: ModelSupervisionKeys.tenants(),
    queryFn: () => listTenants(),
  });
  const allTenants = useMemo(
    () => tenantsResp?.data?.data ?? [],
    [tenantsResp],
  );

  const { data: compareResp, isFetching } = useQuery({
    queryKey: ModelSupervisionKeys.compare(selectedIds),
    queryFn: () => compareTenantModels(selectedIds),
    enabled: selectedIds.length > 0,
    placeholderData: keepPreviousData,
  });
  const compare: CompareResult | undefined = compareResp?.data?.data;

  const emailOf = useMemo(() => {
    const m = new Map(allTenants.map((x) => [x.tenant_id, x.owner_email]));
    return (id: string) => m.get(id) ?? id;
  }, [allTenants]);

  const invalidateCompare = () =>
    queryClient.invalidateQueries({
      queryKey: ['admin/modelSupervision/compare'],
    });

  const closeAction = () => {
    setAction(null);
    setActionSource('');
    setActionTargets(new Set());
  };

  const copyInstanceMut = useMutation({
    mutationFn: (v: {
      source: string;
      provider: string;
      instance: string;
      targets: string[];
    }) => copyModelInstance(v.source, v.provider, v.instance, v.targets),
    onSuccess: () => {
      invalidateCompare();
      closeAction();
    },
  });

  const deleteInstanceMut = useMutation({
    mutationFn: (v: {
      provider: string;
      instance: string;
      targets: string[];
    }) => deleteModelInstance(v.provider, v.instance, v.targets),
    onSuccess: () => {
      invalidateCompare();
      closeAction();
    },
  });

  const copyDefaultsMut = useMutation({
    mutationFn: (v: { source: string; targets: string[] }) =>
      copyModelDefaults(v.source, v.targets),
    onSuccess: () => {
      invalidateCompare();
      closeAction();
    },
  });

  const isPending =
    copyInstanceMut.isPending ||
    deleteInstanceMut.isPending ||
    copyDefaultsMut.isPending;

  const toggleTenant = (id: string) =>
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );

  const toggleTarget = (id: string) =>
    setActionTargets((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });

  const filteredTenants = allTenants.filter((x) =>
    x.owner_email.toLowerCase().includes(pickerFilter.toLowerCase()),
  );

  const columns = compare?.tenants ?? [];

  const filteredModels = (compare?.models ?? []).filter((row) =>
    `${row.provider_name}/${row.instance_name}/${row.model_name}`
      .toLowerCase()
      .includes(modelFilter.toLowerCase()),
  );

  // --- Action dialog openers ---
  const openCopyInstance = (
    providerName: string,
    instanceName: string,
    present: string[],
  ) => {
    setAction({
      kind: 'copyInstance',
      providerName,
      instanceName,
      presentTenantIds: present,
    });
    setActionSource(present[0] ?? '');
    setActionTargets(new Set());
  };
  const openDeleteInstance = (
    providerName: string,
    instanceName: string,
    present: string[],
  ) => {
    setAction({
      kind: 'deleteInstance',
      providerName,
      instanceName,
      presentTenantIds: present,
    });
    setActionSource('');
    setActionTargets(new Set());
  };
  const openCopyDefaults = () => {
    const present = columns.map((c) => c.tenant_id);
    setAction({ kind: 'copyDefaults', presentTenantIds: present });
    setActionSource(present[0] ?? '');
    setActionTargets(new Set());
  };

  // --- Dialog derived data ---
  const sourceCandidates =
    action?.kind === 'copyDefaults'
      ? columns.map((c) => c.tenant_id)
      : (action?.presentTenantIds ?? []);

  const targetCandidates = (() => {
    if (!action) return [];
    if (action.kind === 'deleteInstance') return action.presentTenantIds;
    return allTenants
      .map((x) => x.tenant_id)
      .filter((id) => id !== actionSource);
  })();

  const canSubmit = (() => {
    if (!action) return false;
    if (action.kind === 'deleteInstance') return actionTargets.size > 0;
    return Boolean(actionSource) && actionTargets.size > 0;
  })();

  const submitAction = () => {
    if (!action) return;
    const targets = [...actionTargets].filter((id) => id !== actionSource);
    if (action.kind === 'copyInstance') {
      copyInstanceMut.mutate({
        source: actionSource,
        provider: action.providerName!,
        instance: action.instanceName!,
        targets,
      });
    } else if (action.kind === 'deleteInstance') {
      deleteInstanceMut.mutate({
        provider: action.providerName!,
        instance: action.instanceName!,
        targets: [...actionTargets],
      });
    } else {
      copyDefaultsMut.mutate({ source: actionSource, targets });
    }
  };

  const dialogTitle = action
    ? action.kind === 'copyInstance'
      ? t('modelSupervision.copyInstanceTitle')
      : action.kind === 'deleteInstance'
        ? t('modelSupervision.deleteInstanceTitle')
        : t('modelSupervision.copyDefaultsTitle')
    : '';
  const isDelete = action?.kind === 'deleteInstance';

  return (
    <section className="h-full overflow-x-hidden overflow-y-auto p-6">
      <Spotlight />
      <div className="mb-4">
        <h1 className="text-xl font-semibold">{t('modelSupervision.title')}</h1>
        <p className="text-sm text-muted-foreground">
          {t('modelSupervision.subtitle')}
        </p>
      </div>

      {/* Tenant picker */}
      <div className="mb-6 flex flex-wrap items-center gap-2">
        {selectedIds.map((id) => (
          <Badge key={id} variant="secondary" className="gap-1">
            {emailOf(id)}
            <button
              type="button"
              onClick={() => toggleTenant(id)}
              aria-label="remove"
            >
              <LucideX className="size-3" />
            </button>
          </Badge>
        ))}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1">
              <LucidePlus className="size-4" />
              {t('modelSupervision.addTenant')}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-80 p-2" align="start">
            <Input
              value={pickerFilter}
              onChange={(e) => setPickerFilter(e.target.value)}
              placeholder={t('modelSupervision.filterTenant')}
              className="mb-2"
            />
            <div className="max-h-72 overflow-y-auto">
              {filteredTenants.map((x) => (
                <label
                  key={x.tenant_id}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-muted"
                >
                  <Checkbox
                    checked={selectedIds.includes(x.tenant_id)}
                    onCheckedChange={() => toggleTenant(x.tenant_id)}
                  />
                  <span className="truncate text-sm">{x.owner_email}</span>
                </label>
              ))}
            </div>
          </PopoverContent>
        </Popover>
      </div>

      {selectedIds.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {t('modelSupervision.selectTenantsHint')}
        </p>
      )}

      {selectedIds.length > 0 && compare && (
        <div className={isFetching ? 'opacity-60' : ''}>
          {/* Providers & instances */}
          <Card className="mb-4">
            <CardHeader>
              <CardTitle>{t('modelSupervision.providersInstances')}</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      {t('modelSupervision.providerInstance')}
                    </TableHead>
                    {columns.map((col) => (
                      <TableHead key={col.tenant_id}>
                        {col.owner_email}
                      </TableHead>
                    ))}
                    <TableHead className="text-right">
                      {t('modelSupervision.actions')}
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {compare.instances.map((row) => {
                    const present = columns
                      .map((c) => c.tenant_id)
                      .filter((id) => row.by_tenant[id]);
                    return (
                      <TableRow
                        key={`${row.provider_name}/${row.instance_name}`}
                      >
                        <TableCell className="font-medium">
                          {row.provider_name} / {row.instance_name}
                        </TableCell>
                        {columns.map((col) => {
                          const cell = row.by_tenant[col.tenant_id];
                          return (
                            <TableCell key={col.tenant_id}>
                              {cell ? (
                                <span className="flex items-center gap-1">
                                  <LucideCheck className="size-4 text-green-600" />
                                  {cell.has_api_key ? (
                                    <code className="text-xs">
                                      {cell.api_key_hint}
                                    </code>
                                  ) : (
                                    <Badge variant="destructive">
                                      {t('modelSupervision.noApiKey')}
                                    </Badge>
                                  )}
                                </span>
                              ) : (
                                <span className="text-muted-foreground">
                                  {EMPTY}
                                </span>
                              )}
                            </TableCell>
                          );
                        })}
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="outline"
                              size="sm"
                              className="gap-1"
                              onClick={() =>
                                openCopyInstance(
                                  row.provider_name,
                                  row.instance_name,
                                  present,
                                )
                              }
                            >
                              <LucideCopy className="size-3" />
                              {t('modelSupervision.copy')}
                            </Button>
                            <Button
                              variant="outline"
                              size="sm"
                              className="gap-1 text-destructive"
                              onClick={() =>
                                openDeleteInstance(
                                  row.provider_name,
                                  row.instance_name,
                                  present,
                                )
                              }
                            >
                              <LucideTrash2 className="size-3" />
                              {t('modelSupervision.delete')}
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Default models */}
          <Card className="mb-4">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('modelSupervision.defaultModels')}</CardTitle>
              <Button
                variant="outline"
                size="sm"
                className="gap-1"
                onClick={openCopyDefaults}
              >
                <LucideCopy className="size-3" />
                {t('modelSupervision.copyDefaultsTo')}
              </Button>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('modelSupervision.type')}</TableHead>
                    {columns.map((col) => (
                      <TableHead key={col.tenant_id}>
                        {col.owner_email}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {compare.defaults.map((row) => (
                    <TableRow key={row.model_type}>
                      <TableCell className="font-medium">
                        {row.model_type}
                      </TableCell>
                      {columns.map((col) => {
                        const cell = row.by_tenant[col.tenant_id];
                        return (
                          <TableCell key={col.tenant_id}>
                            {cell ? (
                              <span className="flex items-center gap-1">
                                <code className="text-xs">{cell.value}</code>
                                {!cell.resolvable && (
                                  <Badge variant="destructive">
                                    {t('modelSupervision.dangling')}
                                  </Badge>
                                )}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">
                                {EMPTY}
                              </span>
                            )}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Added models (catalog) */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('modelSupervision.addedModels')}</CardTitle>
              <Input
                value={modelFilter}
                onChange={(e) => setModelFilter(e.target.value)}
                placeholder={t('modelSupervision.filterModel')}
                className="w-64"
              />
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('modelSupervision.model')}</TableHead>
                    {columns.map((col) => (
                      <TableHead key={col.tenant_id}>
                        {col.owner_email}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredModels.map((row) => (
                    <TableRow
                      key={`${row.provider_name}/${row.instance_name}/${row.model_name}`}
                    >
                      <TableCell className="font-medium">
                        {row.provider_name} / {row.instance_name} /{' '}
                        {row.model_name}
                      </TableCell>
                      {columns.map((col) => {
                        const cell = row.by_tenant[col.tenant_id];
                        return (
                          <TableCell key={col.tenant_id}>
                            {cell ? (
                              <span className="flex flex-wrap items-center gap-1">
                                <LucideCheck className="size-4 text-green-600" />
                                {cell.model_type.map((mt) => (
                                  <Badge key={mt} variant="outline">
                                    {mt}
                                  </Badge>
                                ))}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">
                                {EMPTY}
                              </span>
                            )}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Action dialog (copy instance / delete instance / copy defaults) */}
      <Dialog
        open={action !== null}
        onOpenChange={(open) => !open && closeAction()}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{dialogTitle}</DialogTitle>
            {action?.providerName && (
              <DialogDescription>
                {action.providerName} / {action.instanceName}
              </DialogDescription>
            )}
          </DialogHeader>

          {/* Source selector (copy operations only) */}
          {action && !isDelete && (
            <div>
              <p className="mb-1 text-sm font-medium">
                {t('modelSupervision.source')}
              </p>
              <div className="flex flex-wrap gap-2">
                {sourceCandidates.map((id) => (
                  <Button
                    key={id}
                    size="sm"
                    variant={actionSource === id ? 'default' : 'outline'}
                    onClick={() => setActionSource(id)}
                  >
                    {emailOf(id)}
                  </Button>
                ))}
              </div>
            </div>
          )}

          <div
            className={
              isDelete
                ? 'rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive'
                : 'rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-sm'
            }
          >
            {isDelete
              ? t('modelSupervision.deleteWarning')
              : t('modelSupervision.copyWarning')}
          </div>

          <div className="max-h-60 overflow-y-auto">
            <p className="mb-1 text-sm font-medium">
              {t('modelSupervision.targets')}
            </p>
            {targetCandidates.map((id) => (
              <label
                key={id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-muted"
              >
                <Checkbox
                  checked={actionTargets.has(id)}
                  onCheckedChange={() => toggleTarget(id)}
                />
                <span className="truncate text-sm">{emailOf(id)}</span>
              </label>
            ))}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeAction}>
              {t('modelSupervision.cancel')}
            </Button>
            <Button
              variant={isDelete ? 'destructive' : 'default'}
              disabled={!canSubmit || isPending}
              onClick={submitAction}
            >
              {isDelete
                ? isPending
                  ? t('modelSupervision.deleting')
                  : t('modelSupervision.delete')
                : isPending
                  ? t('modelSupervision.copying')
                  : t('modelSupervision.copy')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default ModelSupervisionPage;
