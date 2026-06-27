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
import { LucideCheck, LucideCopy, LucidePlus, LucideX } from 'lucide-react';

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
  copyTenantModels,
} from '@/services/admin-model-supervision-service';
import { listTenants } from '@/services/admin-service';

const ModelSupervisionKeys = {
  tenants: () => ['admin/modelSupervision/tenants'] as const,
  compare: (ids: string[]) =>
    ['admin/modelSupervision/compare', [...ids].sort().join(',')] as const,
};

const EMPTY = '—';

function ModelSupervisionPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [pickerFilter, setPickerFilter] = useState('');
  const [copySource, setCopySource] = useState<string | null>(null);
  const [copyTargets, setCopyTargets] = useState<Set<string>>(new Set());

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

  const copyMutation = useMutation({
    mutationFn: async ({
      source,
      targets,
    }: {
      source: string;
      targets: string[];
    }) => {
      for (const target of targets) {
        await copyTenantModels(target, source);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/modelSupervision/compare'],
      });
      setCopySource(null);
      setCopyTargets(new Set());
    },
  });

  const toggleTenant = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const filteredTenants = allTenants.filter((x) =>
    x.owner_email.toLowerCase().includes(pickerFilter.toLowerCase()),
  );

  const columns = compare?.tenants ?? [];

  const openCopyDialog = (sourceId: string) => {
    setCopySource(sourceId);
    setCopyTargets(new Set());
  };

  const copyCandidates = allTenants.filter((x) => x.tenant_id !== copySource);

  return (
    <section className="p-6">
      <Spotlight />
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            {t('modelSupervision.title')}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t('modelSupervision.subtitle')}
          </p>
        </div>
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
          {/* Column actions */}
          <div
            className="mb-4 grid gap-2"
            style={{
              gridTemplateColumns: `220px repeat(${columns.length}, minmax(180px, 1fr))`,
            }}
          >
            <div />
            {columns.map((col) => (
              <Button
                key={col.tenant_id}
                variant="outline"
                size="sm"
                className="gap-1"
                onClick={() => openCopyDialog(col.tenant_id)}
              >
                <LucideCopy className="size-3" />
                {t('modelSupervision.copyTo')}
              </Button>
            ))}
          </div>

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
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {compare.instances.map((row) => (
                    <TableRow key={`${row.provider_name}/${row.instance_name}`}>
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
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Default models */}
          <Card className="mb-4">
            <CardHeader>
              <CardTitle>{t('modelSupervision.defaultModels')}</CardTitle>
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
            <CardHeader>
              <CardTitle>
                {t('modelSupervision.addedModels')} ({compare.models.length})
              </CardTitle>
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
                  {compare.models.map((row) => (
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

      {/* Copy dialog */}
      <Dialog
        open={copySource !== null}
        onOpenChange={(open) => !open && setCopySource(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('modelSupervision.copyDialogTitle')}</DialogTitle>
            <DialogDescription>
              {t('modelSupervision.copyFrom', {
                email: copySource ? emailOf(copySource) : '',
              })}
            </DialogDescription>
          </DialogHeader>

          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive">
            {t('modelSupervision.copyWarning')}
          </div>

          <div className="max-h-72 overflow-y-auto">
            <p className="mb-1 text-sm font-medium">
              {t('modelSupervision.targets')}
            </p>
            {copyCandidates.map((x) => (
              <label
                key={x.tenant_id}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-muted"
              >
                <Checkbox
                  checked={copyTargets.has(x.tenant_id)}
                  onCheckedChange={() =>
                    setCopyTargets((prev) => {
                      const next = new Set(prev);
                      if (next.has(x.tenant_id)) {
                        next.delete(x.tenant_id);
                      } else {
                        next.add(x.tenant_id);
                      }
                      return next;
                    })
                  }
                />
                <span className="truncate text-sm">{x.owner_email}</span>
              </label>
            ))}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCopySource(null)}>
              {t('modelSupervision.cancel')}
            </Button>
            <Button
              disabled={copyTargets.size === 0 || copyMutation.isPending}
              onClick={() =>
                copySource &&
                copyMutation.mutate({
                  source: copySource,
                  targets: [...copyTargets],
                })
              }
            >
              {copyMutation.isPending
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
