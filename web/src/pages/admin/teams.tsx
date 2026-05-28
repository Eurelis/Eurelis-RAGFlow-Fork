import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';

import { LucideArrowRight, LucideSearch } from 'lucide-react';

import { useQuery } from '@tanstack/react-query';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  useReactTable,
} from '@tanstack/react-table';

import { Routes } from '@/routes';

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { TableEmpty } from '@/components/table-skeleton';
import { listTenants } from '@/services/admin-service';

const columnHelper = createColumnHelper<AdminService.ListTenantsItem>();

function AdminTeams() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');

  const { data: tenants = [] } = useQuery({
    queryKey: ['admin/listTenants'],
    queryFn: async () => (await listTenants()).data.data,
    retry: false,
  });

  const columnDefs = useMemo(
    () => [
      columnHelper.accessor('owner_email', {
        header: t('admin.owner'),
        cell: ({ row, cell }) => (
          <div className="flex items-center gap-2">
            <RAGFlowAvatar name={cell.getValue()} />
            <div className="flex flex-col">
              <span>{cell.getValue()}</span>
              {row.original.owner_nickname && (
                <span className="text-xs text-text-secondary">
                  {row.original.owner_nickname}
                </span>
              )}
            </div>
          </div>
        ),
      }),
      columnHelper.accessor('member_count', {
        header: t('admin.memberCount'),
      }),
      columnHelper.display({
        id: 'actions',
        header: t('admin.actions'),
        cell: ({ row }) => (
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={() =>
              navigate(Routes.AdminTeams + '/' + row.original.tenant_id)
            }
          >
            {t('admin.teamManagement')}
            <LucideArrowRight className="size-4" />
          </Button>
        ),
      }),
    ],
    [t, navigate],
  );

  const table = useReactTable({
    data: tenants,
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    state: {
      globalFilter: search,
    },
    onGlobalFilterChange: setSearch,
    globalFilterFn: (row, _columnId, filterValue) =>
      row.original.owner_email
        .toLowerCase()
        .includes(filterValue.toLowerCase()) ||
      row.original.owner_nickname
        ?.toLowerCase()
        .includes(filterValue.toLowerCase()),
    enableSorting: false,
  });

  return (
    <section className="px-10 py-5 size-full flex flex-col">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">{t('admin.teamManagement')}</h1>
      </div>

      <div className="relative mb-4 max-w-sm">
        <LucideSearch className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-text-secondary" />
        <Input
          className="pl-9"
          placeholder={t('admin.email')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmpty columnsLength={columnDefs.length} />
            )}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

export default AdminTeams;
