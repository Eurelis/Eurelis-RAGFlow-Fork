import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import {
  LucideArrowLeft,
  LucideCheckCircle,
  LucideDot,
  LucidePlus,
  LucideTrash2,
} from 'lucide-react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from '@tanstack/react-table';

import { Routes } from '@/routes';

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import Spotlight from '@/components/spotlight';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { RAGFlowPagination } from '@/components/ui/ragflow-pagination';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Table, TableBody, TableCell, TableRow } from '@/components/ui/table';

import {
  addTenantMember,
  getUserDetails,
  listUserTenants,
  removeTenantMember,
  updateTenantMemberRole,
} from '@/services/admin-service';

import { TableEmpty } from '@/components/table-skeleton';
import EnterpriseFeature from './components/enterprise-feature';
import useAddToTeamForm from './forms/add-to-team-form';
import { parseBooleanish } from './utils';

const teamColumnHelper =
  createColumnHelper<AdminService.UserTenantMembership>();

function UserTeamTable(props: {
  userId: string;
  data?: AdminService.UserTenantMembership[];
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const { id: formId, form, FormComponent } = useAddToTeamForm();

  const removeMutation = useMutation({
    mutationFn: ({ tenantId }: { tenantId: string }) =>
      removeTenantMember(tenantId, props.userId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/userTeams', props.userId],
      });
    },
  });

  const addMutation = useMutation({
    mutationFn: ({ tenantId, role }: { tenantId: string; role: string }) =>
      addTenantMember(tenantId, props.userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/userTeams', props.userId],
      });
      setAddDialogOpen(false);
      form.reset();
    },
  });

  const validateMutation = useMutation({
    mutationFn: (tenantId: string) =>
      updateTenantMemberRole(tenantId, props.userId, 'normal'),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/userTeams', props.userId],
      });
    },
  });

  const columnDefs = useMemo(
    () => [
      teamColumnHelper.accessor('email', {
        header: t('admin.owner'),
        cell: ({ row, cell }) => (
          <div className="flex items-center gap-2">
            <RAGFlowAvatar
              avatar={row.original.avatar}
              name={cell.getValue()}
            />
            <div className="flex flex-col">
              <span>{cell.getValue()}</span>
              {row.original.nickname && (
                <span className="text-xs text-text-secondary">
                  {row.original.nickname}
                </span>
              )}
            </div>
          </div>
        ),
      }),
      teamColumnHelper.accessor('role', {
        header: t('admin.teamMemberRole'),
        cell: ({ cell }) => (
          <Badge variant="secondary">{cell.getValue()}</Badge>
        ),
      }),
      teamColumnHelper.accessor('update_date', {
        header: t('admin.addedDate'),
      }),
      teamColumnHelper.display({
        id: 'actions',
        header: t('admin.actions'),
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
            {row.original.role === 'invite' && (
              <Button
                variant="ghost"
                size="icon"
                title={t('admin.validateInvite')}
                onClick={() => validateMutation.mutate(row.original.tenant_id)}
              >
                <LucideCheckCircle className="size-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive hover:text-destructive"
              onClick={() =>
                removeMutation.mutate({ tenantId: row.original.tenant_id })
              }
            >
              <LucideTrash2 className="size-4" />
            </Button>
          </div>
        ),
      }),
    ],
    [t, removeMutation, validateMutation],
  );

  const table = useReactTable({
    data: props.data ?? [],
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    enableSorting: false,
  });

  const excludedTenantIds = (props.data ?? []).map((m) => m.tenant_id);

  return (
    <section className="space-y-4">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          className="gap-2"
          onClick={() => setAddDialogOpen(true)}
        >
          <LucidePlus className="size-4" />
          {t('admin.addTeam')}
        </Button>
      </div>

      <Table>
        <TableBody>
          {table.getRowModel().rows?.length ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableEmpty columnsLength={columnDefs.length} />
          )}
        </TableBody>
      </Table>

      <RAGFlowPagination
        total={props.data?.length}
        current={table.getState().pagination.pageIndex + 1}
        pageSize={table.getState().pagination.pageSize}
        onChange={(page, pageSize) => {
          table.setPagination({ pageIndex: page - 1, pageSize });
        }}
      />

      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.addTeam')}</DialogTitle>
          </DialogHeader>
          <FormComponent
            excludeTenantIds={[props.userId, ...excludedTenantIds]}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              {t('admin.cancel')}
            </Button>
            <Button
              form={formId}
              type="submit"
              disabled={addMutation.isPending}
              onClick={form.handleSubmit((data) =>
                addMutation.mutate({
                  tenantId: data.tenantId,
                  role: 'normal',
                }),
              )}
            >
              {t('admin.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function AdminUserTeam() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { id } = useParams();

  const { data: detail } = useQuery({
    queryKey: ['admin/userDetail', id],
    queryFn: async () => {
      const res = await getUserDetails(id!);
      return res.data.data[0];
    },
    enabled: !!id,
    retry: false,
  });

  const { data: teams } = useQuery({
    queryKey: ['admin/userTeams', detail?.id],
    queryFn: async () => (await listUserTenants(detail!.id)).data.data,
    enabled: !!detail?.id,
    retry: false,
  });

  return (
    <section className="px-10 py-5 size-full flex flex-col">
      <nav className="mb-5">
        <Button
          variant="outline"
          className="h-10 px-3 dark:bg-bg-input dark:border-border-button"
          onClick={() => navigate(`${Routes.AdminUserManagement}`)}
        >
          <LucideArrowLeft />
          <span>{t('admin.back')}</span>
        </Button>
      </nav>

      <Card className="!shadow-none relative h-0 basis-0 grow flex flex-col bg-transparent border-0.5 border-border-button overflow-hidden">
        <Spotlight />

        <CardHeader className="pb-10 border-b-0.5 dark:border-border-button space-y-8">
          <h1 className="text-xl font-semibold">{t('setting.joinedTeams')}</h1>
          <section className="flex items-center gap-4 text-base">
            <RAGFlowAvatar
              avatar={detail?.avatar}
              name={detail?.email}
              isPerson
            />

            <span>{detail?.email}</span>

            <Badge
              variant={
                parseBooleanish(detail?.is_active) ? 'success' : 'destructive'
              }
              className="pl-[.5em]"
            >
              <LucideDot className="size-[1em] stroke-[8] mr-1" />
              {t(
                parseBooleanish(detail?.is_active)
                  ? 'admin.active'
                  : 'admin.inactive',
              )}
            </Badge>

            <EnterpriseFeature>
              {() =>
                detail?.role && (
                  <Badge variant="secondary">{detail?.role}</Badge>
                )
              }
            </EnterpriseFeature>
          </section>
        </CardHeader>

        <CardContent className="h-0 basis-0 grow pt-6">
          <ScrollArea className="h-full">
            <UserTeamTable userId={detail?.id ?? id!} data={teams} />
          </ScrollArea>
        </CardContent>
      </Card>
    </section>
  );
}

export default AdminUserTeam;
